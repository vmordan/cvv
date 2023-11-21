#!/usr/bin/env python3
#
# CVV is a continuous verification visualizer.
# Copyright (c) 2023 ISP RAS (http://www.ispras.ru)
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

from utils.utils import get_args_parser, Session

parser = get_args_parser('Upload comparison data for 2 last children of a given node.')
parser.add_argument('job',
                    help='Node job identifier or its name (note, it must have at least 2 children for comparison)')
parser.add_argument('-o', '--out', help='File name, in which comparison data json will be saved')
parser.add_argument('--redirect-host', dest="redirect", help="Redirect urls to another host:port")
args = parser.parse_args()

with Session(args) as session:
    job_id_or_name = args.job
    data = session.get_comparison_data(job_id_or_name, args.out)
    new_traces_without_marks = int(data['new_traces']) - int(data['new_traces_marked'])
    missing_traces_without_marks = int(data['missing_trace']) - int(data['missing_trace_marked'])
    all_traces_without_marks = int(data['unsafes']) - int(data['unsafes_marked'])
    if args.redirect:
        host = args.redirect
    else:
        host = args.host

    mes = f"### Statistics\n" \
          f" - New issues: {data['new_traces']}, without review: {new_traces_without_marks} " \
          f"({host}/reports/component/{data['root_report']}/unsafes/?cmp={data['compared_job_id']})\n" \
          f" - Missing issues: {data['missing_trace']}, without review: {missing_traces_without_marks} " \
          f"({host}/reports/component/{data['compared_root_report']}/unsafes/?cmp={data['job_id']})\n" \
          f" - Total issues: {data['unsafes']}, without review: {all_traces_without_marks} " \
          f"({host}/reports/component/{data['root_report']}/unsafes/)\n\n" \
          f"### Links\n" \
          f" - Link to the new results: {host}/jobs/{data['job_id']}\n" \
          f" - Link to the previous results: {host}/jobs/{data['compared_job_id']}\n" \
          f" - Link to the comparison with previous results: {host}/reports/comparison/{job_id_or_name}"
    print(mes)
