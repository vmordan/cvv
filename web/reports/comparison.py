#
# CVV is a continuous verification visualizer.
# Copyright (c) 2019-2023 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import sys
from difflib import SequenceMatcher

from jobs.models import Job
from jobs.utils import get_resource_data
from marks.models import MarkUnsafeReport, MarkUnknownReport
from reports.mea.wrapper import COMPARISON_FUNCTIONS, CONVERSION_FUNCTIONS, DEFAULT_SIMILARITY_THRESHOLD, \
    DEFAULT_COMPARISON_FUNCTION, DEFAULT_CONVERSION_FUNCTION, compare_converted_traces, get_or_convert_error_trace_auto
from reports.models import ReportAttr, ReportSafe, ReportUnsafe, ReportUnknown, ReportRoot, ComponentResource

VERDICT_SAFE = 'safe'
VERDICT_UNSAFE = 'unsafe'
VERDICT_UNSAFE_INCOMPLETE = 'unsafe-incomplete'
VERDICT_UNKNOWN = 'unknown'

VERDICTS_SAFE = 'safes'
VERDICTS_UNSAFE = 'unsafes'
VERDICTS_UNSAFE_INCOMPLETE = 'unsafe_incompletes'
VERDICTS_UNKNOWN = 'unknowns'
VERDICTS_ALL = [VERDICTS_SAFE, VERDICTS_UNSAFE, VERDICTS_UNSAFE_INCOMPLETE, VERDICTS_UNKNOWN]

FILTERED_ATTRS = ['Coverage:Functions', 'Coverage:Lines', 'Filtering time', 'Found all traces', 'Traces:Filtered',
                  'Traces:Initial']

CLUSTERING_ORIGIN_MARK = "mark"
CLUSTERING_ORIGIN_AUTO = "auto"

CLUSTERING_TYPE_DIFF_CLUSTERS = "diff_clusters"
CLUSTERING_TYPE_DIFF_TRACES = "diff_traces"
CLUSTERING_TYPE_ALL = "all"

SHOW_PROBLEMS_DIFF = "diff"
SHOW_PROBLEMS_WITHOUT = "without"
SHOW_PROBLEMS_ALL = "all"

TAG_AUTO_ID = "id"
TAG_MARK = "mark"
TAG_ORIGIN = "origin"
TAG_ATTRS = "attrs"
TAG_REPORTS = "reports"
TAG_CET = "cet"
TAG_COLOR = "color"
TAG_HIDE = "hide"

CLUSTERING_COLORS = ["#ebadad", "#adebad"]


class InternalLeaf:
    def __init__(self, verdict: str, cpu_time: int, parent_report_id: int):
        self.verdict = verdict
        self.cpu_time = cpu_time
        if not cpu_time:
            self.cpu_time = 0
        self.parent_report_id = parent_report_id
        self.attrs_vals = dict()
        self.unused_attrs_vals = dict()
        self.attrs_ids = set()

    def add_attrs(self, name: str, val: str, attr_id: int):
        if name not in self.attrs_vals:
            self.attrs_vals[name] = set()
        self.attrs_vals[name].add(val)
        self.attrs_ids.add(attr_id)

    def add_unused_attrs(self, name: str, val: str):
        if name not in self.unused_attrs_vals:
            self.unused_attrs_vals[name] = set()
        self.unused_attrs_vals[name].add(val)

    def serialize_attrs(self, core_attrs: set = set()) -> tuple:
        tmp_res = list()
        tmp_res_core = list()
        for name, vals in sorted(self.attrs_vals.items()):
            for val in sorted(vals):
                tmp_res.append(str(val))
                if name in core_attrs:
                    tmp_res_core.append(str(val))
        return "/".join(tmp_res), "/".join(tmp_res_core)

    def is_attr(self, filtered: dict):
        for name in set(self.attrs_vals.keys()).intersection(filtered.keys()):
            if set(self.attrs_vals[name]).issubset(filtered[name]):
                return True
        return False

    def __str__(self):
        return "[{}, {}, {}]".format(self.verdict, self.cpu_time, self.serialize_attrs()[0])


class JobsComparison:
    def __init__(self, root_reports: list, args: dict = {}, other_jobs: list = [], all_jobs: list = []):
        self.__init_args(args)
        self.all_jobs = all_jobs

        if self.potential_jobs:
            for root in root_reports:
                report_id = root.job.id
                if report_id not in self.potential_jobs:
                    self.potential_jobs.add(report_id)
            if len(self.potential_jobs) > 2:
                other_jobs = self.potential_jobs
            else:
                other_jobs = list()
        if other_jobs:
            self.job_ids = list()
            for job_id, job_name in Job.objects.filter(id__in=other_jobs).order_by('-id').values_list('id', 'name'):
                self.job_ids.append((job_id, job_name))
                self.potential_jobs.add(job_id)

        common_attrs = dict()
        common_attrs_ids = set()
        common_attrs_vals = dict()
        self.uncore_attrs = set()
        self.unused_attrs = list()

        self.internals = list()
        joint_attrs = dict()
        self.comparison = list()
        for root in root_reports:
            self.potential_jobs.add(root.job.id)
            attrs, attrs_vals, attrs_ids, cdata = self.init_internals(root)
            if common_attrs:
                common_attrs, common_attrs_vals = \
                    self.get_common_attrs(attrs, attrs_vals, common_attrs, common_attrs_vals)
                common_attrs_ids.intersection_update(attrs_ids)
            else:
                common_attrs, common_attrs_vals = attrs, attrs_vals
                common_attrs_ids = attrs_ids

            if self.comparison:
                cdata['launches_comp'] = self.comparison[0]['launches'] >= cdata['launches']
                cdata['launches_diff'] = abs(self.comparison[0]['launches'] - cdata['launches'])

            joint_attrs.update(attrs)

            self.comparison.append(cdata)

        self.common_attrs_as_dict = common_attrs
        self.common_attrs, self.common_attrs_vals = self.sort_attrs(common_attrs, common_attrs_vals)
        self.joint_attrs = self.sort_attrs(joint_attrs)[0]

        # 2nd iteration.
        counter = 0
        clusters = list()
        self.cpu_time_first_sum = 0
        self.cpu_time_first = dict()
        unused_attrs_all = list()
        for cmp in self.comparison:
            marked_attrs = list()

            safes, unsafes, unsafe_incompletes, unknowns, cpu_time, unused_attrs = \
                self.sort_internals_by_attrs(counter, common_attrs_ids)
            if self.find_unused_attrs:
                unused_attrs_all.append(unused_attrs)
            self.__process_cpu_time(cpu_time, counter)

            cmp['{}_len'.format(VERDICTS_SAFE)] = len(safes)
            cmp['{}_len'.format(VERDICTS_UNSAFE)] = len(unsafes)
            cmp['{}_len'.format(VERDICTS_UNSAFE_INCOMPLETE)] = len(unsafe_incompletes)
            cmp['{}_len'.format(VERDICTS_UNKNOWN)] = len(unknowns)
            if counter == 0:
                cmp[VERDICTS_UNSAFE] = unsafes
                cmp[VERDICTS_UNSAFE_INCOMPLETE] = unsafe_incompletes
                cmp[VERDICTS_UNKNOWN] = unknowns
                cmp[VERDICTS_SAFE] = safes
            else:
                for verdicts_type in VERDICTS_ALL:
                    self.__process_verdicts_transitions(verdicts_type, safes, unsafes, unsafe_incompletes, unknowns,
                                                        cmp)
                    if not self.show_same_transitions[verdicts_type]:
                        if not (self.show_problems and verdicts_type == VERDICTS_UNKNOWN):
                            cmp['{0}_{0}'.format(verdicts_type)] = []

            if self.enable_clustering:
                clusters.append(self.perform_clustering(unsafes, unsafe_incompletes, cmp))

            for name, vals in cmp['attrs_vals']:
                marked_vals = list()
                other_vals = list()
                for val in vals:
                    if name in common_attrs_vals and val in common_attrs_vals[name]:
                        marked_vals.append((val, True))
                    else:
                        other_vals.append((val, False))
                marked_attrs.append((name, marked_vals + other_vals))
            cmp['attrs_vals'] = marked_attrs
            counter += 1
        self.uncore_attrs = sorted(self.uncore_attrs)

        if clusters:
            # TODO: support for more than 2 reports comparison
            assert len(clusters) == 2
            clusters_1 = clusters[0]
            clusters_2 = clusters[1]

            desc_1 = self.__pre_process_cluster(clusters_1)
            desc_2 = self.__pre_process_cluster(clusters_2)

            common_marks = desc_1.get(CLUSTERING_ORIGIN_MARK, set()). \
                intersection(desc_2.get(CLUSTERING_ORIGIN_MARK, set()))

            if self.clustering_type == CLUSTERING_TYPE_DIFF_TRACES:
                for cluster_1 in clusters_1:
                    if cluster_1[TAG_ORIGIN] == CLUSTERING_ORIGIN_MARK and cluster_1[TAG_MARK] in common_marks:
                        for cluster_2 in clusters_2:
                            if cluster_2[TAG_ORIGIN] == CLUSTERING_ORIGIN_MARK and \
                                    cluster_2[TAG_MARK] == cluster_1[TAG_MARK]:
                                if len(cluster_1[TAG_REPORTS]) == len(cluster_2[TAG_REPORTS]):
                                    cluster_1[TAG_HIDE] = True
                                    cluster_2[TAG_HIDE] = True

            common_compared_attrs = desc_1.get(CLUSTERING_ORIGIN_AUTO, set()). \
                intersection(desc_2.get(CLUSTERING_ORIGIN_AUTO, set()))

            common_ama_counter = 0
            for cluster_1 in clusters_1:
                if cluster_1[TAG_ORIGIN] == CLUSTERING_ORIGIN_AUTO and cluster_1[TAG_ATTRS] in common_compared_attrs:
                    compared_attrs = cluster_1[TAG_ATTRS]
                    cet_1 = cluster_1[TAG_CET]
                    for cluster_2 in clusters_2:
                        if cluster_2[TAG_ORIGIN] == CLUSTERING_ORIGIN_AUTO and cluster_2[TAG_ATTRS] == compared_attrs \
                                and TAG_AUTO_ID not in cluster_2:
                            cet_2 = cluster_2[TAG_CET]
                            if compare_converted_traces(cet_1, cet_2, self.comparison_function, self.similarity):
                                common_ama_counter += 1
                                cluster_1[TAG_AUTO_ID] = common_ama_counter
                                cluster_2[TAG_AUTO_ID] = common_ama_counter
                                if self.clustering_type == CLUSTERING_TYPE_DIFF_TRACES:
                                    if len(cluster_1[TAG_REPORTS]) == len(cluster_2[TAG_REPORTS]):
                                        cluster_1[TAG_HIDE] = True
                                        cluster_2[TAG_HIDE] = True
                                break

            counter = 0
            for cluster in clusters:
                self.comparison[counter]['clusters_len'] = len(cluster)
                common_clusters = len(common_marks) + common_ama_counter
                if counter:
                    self.__post_process_cluster(clusters, common_marks)
                    all_new = 0
                    all_lost = 0
                    am_new = 0
                    am_lost = 0
                    ama_new = 0
                    ama_lost = 0
                    if len(cluster) > common_clusters:
                        all_new = len(cluster) - common_clusters
                    if len(clusters[0]) > common_clusters:
                        all_lost = len(clusters[0]) - common_clusters
                    if len(desc_2.get(CLUSTERING_ORIGIN_MARK, set())) > len(common_marks):
                        am_new = len(desc_2.get(CLUSTERING_ORIGIN_MARK, set())) - len(common_marks)
                    if len(desc_1.get(CLUSTERING_ORIGIN_MARK, set())) > len(common_marks):
                        am_lost = len(desc_1.get(CLUSTERING_ORIGIN_MARK, set())) - len(common_marks)
                    if all_new > am_new:
                        ama_new = all_new - am_new
                    if all_lost > am_lost:
                        ama_lost = all_lost - am_lost
                    self.comparison[counter]['clusters_new'] = all_new
                    self.comparison[counter]['clusters_lost'] = all_lost
                    self.comparison[counter]['clusters_am_new'] = am_new
                    self.comparison[counter]['clusters_am_lost'] = am_lost
                    self.comparison[counter]['clusters_ama_new'] = ama_new
                    self.comparison[counter]['clusters_ama_lost'] = ama_lost

                counter += 1

        # Problems (Unknowns).
        if self.show_problems:
            # Since only 2 reports are supported.
            common_unknowns = self.comparison[1]["{}_{}".format(VERDICTS_UNKNOWN, VERDICTS_UNKNOWN)]
            report_ids = set()
            self.problems_comparison = list()
            for ids_1, attrs, ids_2 in common_unknowns:
                report_ids = report_ids.union(ids_1)
                report_ids = report_ids.union(ids_2)
            id_to_problems = dict()
            for problem, report_id in MarkUnknownReport.objects.filter(report__id__in=report_ids). \
                    values_list('problem__name', 'report_id'):
                if report_id not in id_to_problems:
                    id_to_problems[report_id] = set()
                id_to_problems[report_id].add(problem)
            for ids_1, attrs, ids_2 in common_unknowns:
                problems_1 = set()
                problems_2 = set()
                for report_id in ids_1:
                    if report_id in id_to_problems:
                        problems_1 = problems_1.union(id_to_problems[report_id])
                for report_id in ids_2:
                    if report_id in id_to_problems:
                        problems_2 = problems_2.union(id_to_problems[report_id])
                if problems_1:
                    problems_1 = ", ".join(sorted(problems_1))
                else:
                    problems_1 = "Unmarked"
                if problems_2:
                    problems_2 = ", ".join(sorted(problems_2))
                else:
                    problems_2 = "Unmarked"
                is_add = True
                if not self.show_problems_type == SHOW_PROBLEMS_ALL:
                    if problems_1 == problems_2:
                        is_add = False
                    if self.show_problems_type == SHOW_PROBLEMS_WITHOUT:
                        if problems_1 == "Unmarked":
                            is_add = True
                if is_add:
                    # TODO: maybe could be useful to rewrite for several ids
                    self.problems_comparison.append(((problems_1, ids_1[0]), attrs, (problems_2, ids_2[0])))

        if unused_attrs_all:
            self.__sort_unused_attrs(unused_attrs_all)

    def __process_cpu_time(self, cpu_time_data: tuple, counter: int):
        cpu_sum = 0
        cpu_time_dict = dict()
        for cpu_time, key in cpu_time_data:
            cpu_sum += cpu_time
            cpu_time_dict[key] = cpu_time
        self.comparison[counter]['compared_cpu'] = get_resource_data('hum', 2, ComponentResource(report=None,
                                                                                                 cpu_time=cpu_sum))[1]
        if counter == 0:
            self.cpu_time_first_sum = cpu_sum
            self.cpu_time_first = cpu_time_dict
        else:
            self.comparison[counter]['average_speedup'] = '-'
            self.comparison[counter]['overall_speedup'] = '-'
            if cpu_sum:
                average_speedup = list()
                for key, cpu_time_1 in self.cpu_time_first.items():
                    cpu_time_2 = cpu_time_dict.get(key, 0)
                    if cpu_time_2:
                        average_speedup.append(cpu_time_1 / cpu_time_2)
                if average_speedup:
                    self.comparison[counter]['average_speedup'] = round(sum(average_speedup) / len(average_speedup), 2)
                self.comparison[counter]['overall_speedup'] = round(self.cpu_time_first_sum / cpu_sum, 2)

    def __sort_unused_attrs(self, unused_attrs_all: list):
        unused_attrs_1 = unused_attrs_all[0]
        unused_attrs_2 = unused_attrs_all[1]
        for key, unused_attrs in sorted(unused_attrs_1.items()):
            attrs_1 = list()
            attrs_2 = list()
            is_add = False
            for name in self.unused_attrs_names:
                val_1 = ",".join(unused_attrs.get(name, '-'))
                val_2 = ",".join(unused_attrs_2.get(key, {}).get(name, '-'))
                is_equal = val_1 == val_2
                attrs_1.append((val_1, is_equal))
                attrs_2.append((val_2, is_equal))
                if not is_add and not is_equal:
                    is_add = True
            if is_add:
                self.unused_attrs.append((attrs_1, key, attrs_2))

    def __pre_process_cluster(self, clusters: list) -> dict:
        res = dict()
        for cluster in clusters:
            cluster_origin = cluster[TAG_ORIGIN]
            if cluster_origin not in res:
                res[cluster_origin] = set()
            if cluster_origin == CLUSTERING_ORIGIN_MARK:
                res[cluster_origin].add(cluster[TAG_MARK])
            elif cluster_origin == CLUSTERING_ORIGIN_AUTO:
                res[cluster_origin].add(cluster[TAG_ATTRS])
            else:
                raise Exception("Unknown cluster origin {}".format(cluster_origin))
        return res

    def __post_process_cluster(self, clusters_list: list, common_marks: set):
        common_clusters = list()
        diff_clusters = list()
        counter = 0
        for clusters in clusters_list:
            common_counter = 0
            diff_clusters.append(list())
            for cluster in sorted(clusters,
                                  key=lambda x: (x.get(TAG_MARK, sys.maxsize), x[TAG_ATTRS], x.get(TAG_AUTO_ID, 0))):
                cluster_origin = cluster[TAG_ORIGIN]
                if cluster_origin == CLUSTERING_ORIGIN_MARK:
                    if cluster[TAG_MARK] not in common_marks:
                        self.__change_reports_tag(cluster, counter)
                        cluster[TAG_COLOR] = CLUSTERING_COLORS[counter]
                        diff_clusters[counter].append(cluster)
                    else:
                        self.__process_common_cluster(cluster, common_clusters, counter, common_counter)
                        common_counter += 1
                elif cluster_origin == CLUSTERING_ORIGIN_AUTO:
                    if cluster.get(TAG_AUTO_ID, 0):
                        self.__process_common_cluster(cluster, common_clusters, counter, common_counter)
                        common_counter += 1
                    else:
                        self.__change_reports_tag(cluster, counter)
                        cluster[TAG_COLOR] = CLUSTERING_COLORS[counter]
                        diff_clusters[counter].append(cluster)
                else:
                    raise Exception("Unknown cluster origin {}".format(cluster_origin))
            counter += 1
        self.comparison[counter - 1]['clusters'] = common_clusters + sum(diff_clusters, list())

    def __change_reports_tag(self, cluster: dict, counter: int):
        cluster[TAG_REPORTS + "_{}".format(counter)] = cluster[TAG_REPORTS]
        cluster[TAG_REPORTS] = cluster[TAG_REPORTS][0]

    def __process_common_cluster(self, cluster: dict, common_clusters: list, counter: int, common_counter: int):
        if counter:
            common_clusters[common_counter][TAG_REPORTS + "_{}".format(counter)] = cluster[TAG_REPORTS]
            return
        self.__change_reports_tag(cluster, counter)
        if self.clustering_type == CLUSTERING_TYPE_DIFF_CLUSTERS:
            cluster[TAG_HIDE] = True
        common_clusters.append(cluster)

    def perform_clustering(self, unsafes: dict, unsafe_incompletes: dict, cmp) -> list:
        clusters_by_attrs = dict()
        clusters_by_attrs_reverse = dict()
        traces = set()
        clusters = list()
        for attrs, reports in unsafes.items():
            clusters_by_attrs[attrs] = set(reports)
            for report_id in reports:
                clusters_by_attrs_reverse[report_id] = attrs
            traces.update(reports)
        for attrs, reports in unsafe_incompletes.items():
            unsafe_reports = set()
            for report_id, report_type in reports:
                if report_type == VERDICT_UNSAFE:
                    unsafe_reports.add(report_id)
                    clusters_by_attrs_reverse[report_id] = attrs
            clusters_by_attrs[attrs] = set(unsafe_reports)
            traces.update(unsafe_reports)
        cmp['error_traces'] = len(traces)

        mark_to_reports = dict()
        for mark_id, report_id in MarkUnsafeReport.objects.filter(report__id__in=traces). \
                values_list('mark__id', 'report__id'):
            if mark_id not in mark_to_reports:
                mark_to_reports[mark_id] = set()
            mark_to_reports[mark_id].add(report_id)
            if report_id in traces:
                traces.remove(report_id)

        for mark_id, report_ids in mark_to_reports.items():
            attrs = ""
            for report_id in report_ids:
                report_attrs = clusters_by_attrs_reverse[report_id]
                if attrs:
                    match = SequenceMatcher(None, attrs, report_attrs). \
                        find_longest_match(0, len(attrs), 0, len(report_attrs))
                    attrs = attrs[match.a: match.a + match.size]
                else:
                    attrs = report_attrs
            clusters.append({
                TAG_ATTRS: attrs,
                TAG_ORIGIN: CLUSTERING_ORIGIN_MARK,
                TAG_MARK: mark_id,
                TAG_REPORTS: sorted(report_ids)
            })
        cmp['cluster_marks'] = len(mark_to_reports)

        auto_clusters_counter = 0
        for attrs, reports in clusters_by_attrs.items():
            converted_error_traces = dict()
            for report_id in sorted(reports):
                if report_id not in traces:
                    # There is a mark for this trace.
                    continue
                converted_error_trace = get_or_convert_error_trace_auto(report_id, self.conversion_function, {})
                if not converted_error_traces:
                    converted_error_traces[converted_error_trace] = {report_id}
                else:
                    is_equal = False
                    for processed_cet in converted_error_traces.keys():
                        if compare_converted_traces(converted_error_trace, processed_cet, self.comparison_function,
                                                    self.similarity):
                            is_equal = True
                            converted_error_traces[processed_cet].add(report_id)
                            break
                    if not is_equal:
                        converted_error_traces[converted_error_trace] = {report_id}
            if converted_error_traces:
                for cet, report_ids in converted_error_traces.items():
                    clusters.append({
                        TAG_ATTRS: attrs,
                        TAG_ORIGIN: CLUSTERING_ORIGIN_AUTO,
                        TAG_CET: cet,
                        TAG_REPORTS: sorted(report_ids)
                    })
                    auto_clusters_counter += 1

        cmp['cluster_ama'] = auto_clusters_counter
        return clusters

    def __init_args(self, args: dict):
        # Default values.
        self.show_same_transitions = {
            VERDICTS_SAFE: False,
            VERDICTS_UNSAFE: False,
            VERDICTS_UNSAFE_INCOMPLETE: False,
            VERDICTS_UNKNOWN: False
        }
        self.show_lost_transitions = {
            VERDICT_SAFE: False,
            VERDICT_UNSAFE: False,
            VERDICT_UNKNOWN: False
        }
        self.comparison_attrs = set()
        self.filtered_values = dict()
        self.is_modified = False
        self.core_attrs = set()
        self.core_keys = dict()
        self.core_keys_inverse = dict()
        self.find_unused_attrs = False
        self.unused_attrs_names = dict()

        # MEA.
        self.enable_clustering = True
        self.conversion_functions = CONVERSION_FUNCTIONS
        self.comparison_functions = COMPARISON_FUNCTIONS
        self.similarity = DEFAULT_SIMILARITY_THRESHOLD
        self.conversion_function = DEFAULT_CONVERSION_FUNCTION
        self.comparison_function = DEFAULT_COMPARISON_FUNCTION
        self.clustering_type = CLUSTERING_TYPE_DIFF_CLUSTERS

        # Problems (Unknowns).
        self.show_problems = False
        self.show_problems_type = SHOW_PROBLEMS_DIFF

        self.potential_jobs = set()
        if args:
            self.is_modified = True
            if 'same_transitions' in args:
                same_transitions = args.get('same_transitions', [])
                for verdicts in self.show_same_transitions:
                    self.show_same_transitions[verdicts] = verdicts in same_transitions
            if 'lost_transitions' in args:
                lost_transitions = args.get('lost_transitions', [])
                for verdicts in self.show_lost_transitions:
                    self.show_lost_transitions[verdicts] = verdicts in lost_transitions
            if 'diff_attrs' in args:
                self.unused_attrs_names = args.get('diff_attrs', [])
                if self.unused_attrs_names:
                    self.find_unused_attrs = True
            self.comparison_attrs = set(args.get('comparison_attrs', set()))
            for arg in args.get('filtered_values', {}):
                name, value = str(arg).split("<::>")
                if name not in self.filtered_values:
                    self.filtered_values[name] = set()
                self.filtered_values[name].add(value)
            if 'mea_config' in args:
                mea_config = args.get('mea_config', {})
                self.enable_clustering = mea_config.get('enable', self.enable_clustering)
                self.conversion_function = mea_config.get('conversion', self.conversion_function)
                self.comparison_function = mea_config.get('comparison', self.comparison_function)
                self.similarity = int(mea_config.get('similarity', self.similarity))
                self.clustering_type = mea_config.get('clustering_type', self.clustering_type)
            if 'problems_config' in args:
                problems_config = args.get('problems_config', {})
                self.show_problems = problems_config.get('enable', self.show_problems)
                self.show_problems_type = problems_config.get('show_problems_type', self.show_problems_type)
            if 'selected_jobs' in args:
                for job_id in args.get('selected_jobs', []):
                    self.potential_jobs.add(int(job_id))

    def __process_verdicts_transitions(self, verdicts_type: str, safes: dict, unsafes: dict, unsafe_incompletes: dict,
                                       unknowns: dict, cmp: dict) -> None:
        to_safes = list()
        to_unsafes = list()
        to_unsafe_incompletes = list()
        to_unknowns = list()
        first_reports = self.comparison[0].get(verdicts_type)
        old_reports_number = len(first_reports)
        for cur_attrs, old_reports in first_reports.items():
            if cur_attrs in safes:
                to_safes.append((old_reports, cur_attrs, safes[cur_attrs]))
            elif cur_attrs in unsafes:
                to_unsafes.append((old_reports, cur_attrs, unsafes[cur_attrs]))
            elif cur_attrs in unsafe_incompletes:
                to_unsafe_incompletes.append((old_reports, cur_attrs, unsafe_incompletes[cur_attrs]))
            elif cur_attrs in unknowns:
                to_unknowns.append((old_reports, cur_attrs, unknowns[cur_attrs]))
            else:
                core_cur_attrs = self.core_keys[cur_attrs]
                if core_cur_attrs in safes:
                    to_safes.append((old_reports, cur_attrs, safes[core_cur_attrs]))
                elif core_cur_attrs in unsafes:
                    to_unsafes.append((old_reports, cur_attrs, unsafes[core_cur_attrs]))
                elif core_cur_attrs in unsafe_incompletes:
                    to_unsafe_incompletes.append((old_reports, cur_attrs, unsafe_incompletes[core_cur_attrs]))
                elif core_cur_attrs in unknowns:
                    to_unknowns.append((old_reports, cur_attrs, unknowns[core_cur_attrs]))
                else:
                    core_cur_attrs = self.core_keys_inverse.get(cur_attrs)
                    if core_cur_attrs in safes:
                        to_safes.append((old_reports, cur_attrs, safes[core_cur_attrs]))
                    elif core_cur_attrs in unsafes:
                        to_unsafes.append((old_reports, cur_attrs, unsafes[core_cur_attrs]))
                    elif core_cur_attrs in unsafe_incompletes:
                        to_unsafe_incompletes.append((old_reports, cur_attrs, unsafe_incompletes[core_cur_attrs]))
                    elif core_cur_attrs in unknowns:
                        to_unknowns.append((old_reports, cur_attrs, unknowns[core_cur_attrs]))
                    else:
                        print("Warning: lost transition from reports {} for attrs {} (core attrs are {})".
                              format(old_reports, cur_attrs, core_cur_attrs))

        cmp['{}_safes'.format(verdicts_type)] = sorted(to_safes, key=lambda x: x[1])
        cmp['{}_unsafes'.format(verdicts_type)] = sorted(to_unsafes, key=lambda x: x[1])
        cmp['{}_unsafe_incompletes'.format(verdicts_type)] = sorted(to_unsafe_incompletes, key=lambda x: x[1])
        cmp['{}_unknowns'.format(verdicts_type)] = sorted(to_unknowns, key=lambda x: x[1])
        if verdicts_type == VERDICTS_SAFE:
            lost_verdicts = old_reports_number - len(to_safes)
            new_reports = len(safes)
        elif verdicts_type == VERDICTS_UNSAFE:
            lost_verdicts = old_reports_number - len(to_unsafes)
            new_reports = len(unsafes)
        elif verdicts_type == VERDICTS_UNSAFE_INCOMPLETE:
            lost_verdicts = old_reports_number - len(to_unsafe_incompletes)
            new_reports = len(unsafe_incompletes)
        else:
            lost_verdicts = old_reports_number - len(to_unknowns)
            new_reports = len(unknowns)
        cmp['{}_lost'.format(verdicts_type)] = lost_verdicts
        cmp['{}_new'.format(verdicts_type)] = new_reports - len(first_reports) + lost_verdicts

    def sort_internals_by_attrs(self, number: int, common_attrs_ids: set) -> tuple:
        safes = dict()
        unsafes = dict()
        unsafe_incompletes = dict()
        unknowns = dict()
        cpu_sum = dict()
        diff_attrs = dict()
        attrs = dict()

        verdicts_by_attrs = dict()
        ids_by_attrs = dict()
        lost = set()
        for report_id, internal in self.internals[number].items():

            if self.filtered_values:
                if internal.is_attr(self.filtered_values):
                    continue

            key, key_core = internal.serialize_attrs(self.core_attrs)
            self.core_keys[key] = key_core
            self.core_keys_inverse[key_core] = key
            if not internal.attrs_ids:
                continue
            verdict = internal.verdict
            if not set(internal.attrs_ids).issubset(common_attrs_ids):
                if self.show_lost_transitions[verdict]:
                    lost.add(report_id)
                continue
            if key in attrs:
                for name, vals in internal.unused_attrs_vals.items():
                    if name not in attrs[key]:
                        attrs[key][name] = set()
                    attrs[key][name].update(vals)
            else:
                attrs[key] = internal.unused_attrs_vals.copy()
            if key not in verdicts_by_attrs:
                verdicts_by_attrs[key] = verdict
                ids_by_attrs[key] = {report_id: verdict}
                cpu_sum[internal.parent_report_id] = (internal.cpu_time, key_core)
            else:
                ids_by_attrs[key][report_id] = verdict
                old_verdict = verdicts_by_attrs[key]
                if old_verdict == VERDICT_UNSAFE and verdict == VERDICT_UNKNOWN or \
                        verdict == VERDICT_UNSAFE and old_verdict == VERDICT_UNKNOWN:
                    verdicts_by_attrs[key] = VERDICT_UNSAFE_INCOMPLETE
                elif old_verdict in [VERDICT_UNSAFE, VERDICT_UNSAFE_INCOMPLETE] and verdict == VERDICT_UNSAFE:
                    pass
                else:
                    print("Warning: strange verdicts: {} and {} for attrs {}: {}".format(old_verdict, verdict, key,
                                                                                         internal))

        self.comparison[number]['elems_by_attrs'] = len(verdicts_by_attrs)

        for key, verdict in verdicts_by_attrs.items():
            result = ids_by_attrs[key]
            diff_attrs[key] = attrs[key]
            if verdict == VERDICT_SAFE:
                safes[key] = sorted(result.keys())
            elif verdict == VERDICT_UNSAFE:
                unsafes[key] = sorted(result.keys())
            elif verdict == VERDICT_UNSAFE_INCOMPLETE:
                unsafe_incompletes[key] = sorted(result.items())
            elif verdict == VERDICT_UNKNOWN:
                unknowns[key] = sorted(result.keys())
            else:
                raise Exception("Broken verdict: {}".format(verdict))

        if lost:
            lost_prepared = dict()
            for report_id in sorted(lost):
                internal = self.internals[number][report_id]
                verdict = internal.verdict
                key = internal.serialize_attrs()[0]
                if verdict not in lost_prepared:
                    lost_prepared[verdict] = list()
                lost_prepared[verdict].append({
                    'id': report_id,
                    'attrs': key
                })
            self.comparison[number]['lost'] = lost_prepared

        return safes, unsafes, unsafe_incompletes, unknowns, cpu_sum.values(), diff_attrs

    def sort_attrs(self, attrs: dict, attrs_vals: dict = {}) -> tuple:
        attrs_selected = list()
        attrs_others = list()
        attrs_vals_selected = list()
        attrs_vals_others = list()
        for name, compare in sorted(attrs.items()):
            if compare:
                attrs_selected.append((name, True))
                if attrs_vals:
                    attrs_vals_selected.append((name, attrs_vals[name]))
            else:
                attrs_others.append((name, False))
                if attrs_vals:
                    attrs_vals_others.append((name, attrs_vals[name]))
        sorted_attrs = attrs_selected + attrs_others
        sorted_attrs_vals = attrs_vals_selected + attrs_vals_others
        return sorted_attrs, sorted_attrs_vals

    def get_common_attrs(self, attrs1: dict, attrs_vals1: dict, attrs2: dict, attrs_vals2: dict) -> tuple:
        attrs = dict()
        attrs_vals = dict()
        for attr in set(attrs1.keys()).intersection(attrs2.keys()):
            attrs[attr] = attrs1[attr]
        for attr in attrs.keys():
            attrs_vals[attr] = sorted(set(attrs_vals1[attr]).intersection(set(attrs_vals2[attr])))
        return attrs, attrs_vals

    def init_internals(self, root: ReportRoot) -> tuple:
        """
        Get all required information about the given report from the database.
        """

        comparison_data = {
            'job': root.job,
            'other_components_unknowns': list(),
        }
        overall_resources = ComponentResource.objects.filter(report__root=root, report__parent=None,
                                                             component__name="Core"). \
            values_list('wall_time', 'cpu_time', 'memory')
        if overall_resources:
            wall, cpu, mem = overall_resources.first()
            comparison_data['overall_wall'], comparison_data['overall_cpu'], comparison_data['overall_mem'] = \
                get_resource_data('hum', 2, ComponentResource(wall_time=wall, cpu_time=cpu, memory=mem))
        else:
            comparison_data['overall_wall'], comparison_data['overall_cpu'], comparison_data['overall_mem'] = (0, 0, 0)

        internals = dict()
        verifier_components = set()
        other_components_unknowns = dict()
        for report_id, cpu_time, parent_report_id in ReportUnsafe.objects.filter(root=root). \
                values_list('id', 'cpu_time', 'parent__id'):
            internals[report_id] = InternalLeaf(VERDICT_UNSAFE, cpu_time, parent_report_id)
            verifier_components.add(parent_report_id)
        for report_id, cpu_time, parent_report_id in ReportSafe.objects.filter(root=root). \
                values_list('id', 'cpu_time', 'parent__id'):
            internals[report_id] = InternalLeaf(VERDICT_SAFE, cpu_time, parent_report_id)
            verifier_components.add(parent_report_id)
        for report_id, cpu_time, parent_report_id, component, verification in ReportUnknown.objects.filter(root=root). \
                values_list('id', 'cpu_time', 'parent__id', 'component__name', 'parent__reportcomponent__verification'):
            if verification:
                verifier_components.add(parent_report_id)
                internals[report_id] = InternalLeaf(VERDICT_UNKNOWN, cpu_time, parent_report_id)
            else:
                other_components_unknowns[report_id] = component

        comparison_data['launches'] = len(verifier_components)
        other_components_problems = dict()
        for problem, report_id in MarkUnknownReport.objects.filter(report__id__in=other_components_unknowns.keys()). \
                values_list('problem__name', 'report_id'):
            if report_id not in other_components_problems:
                other_components_problems[report_id] = set()
            other_components_problems[report_id].add(problem)

        for report_id, component in sorted(other_components_unknowns.items()):
            if report_id in other_components_problems:
                problem = ", ".join(sorted(other_components_problems[report_id]))
            else:
                problem = None
            comparison_data['other_components_unknowns'].append({
                "id": report_id,
                "component": component,
                "problem": problem
            })

        attrs = dict()
        attrs_vals = dict()
        attrs_ids = set()
        for report_id, attr_id, name, val, compare in ReportAttr.objects.filter(report__in=internals.keys()). \
                values_list('report__id', 'attr_id', 'attr__name__name', 'attr__value', 'associate'):
            if compare:
                self.core_attrs.add(name)
            if self.comparison_attrs:
                compare = name in self.comparison_attrs
            if not compare:
                internals[report_id].add_unused_attrs(name, val)
                if name not in self.uncore_attrs:
                    self.uncore_attrs.add(name)
            if name in FILTERED_ATTRS:
                continue
            if name not in attrs:
                attrs[name] = compare
            if name not in attrs_vals:
                attrs_vals[name] = set()
            attrs_vals[name].add(val)
            if compare:
                attrs_ids.add(attr_id)
                internals[report_id].add_attrs(name, val, attr_id)
        self.internals.append(internals)
        for attr in attrs.keys():
            attrs_vals[attr] = sorted(attrs_vals[attr])

        comparison_data['attrs_vals'] = self.sort_attrs(attrs, attrs_vals)[1]
        comparison_data['attrs'] = attrs

        return attrs, attrs_vals, attrs_ids, comparison_data
