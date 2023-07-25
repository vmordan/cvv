#
# CVV is a continuous verification visualizer.
# Copyright (c) 2023 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
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

import datetime
import glob
import os
import shutil
import subprocess
import time
from io import BytesIO
from typing import Optional

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files import File as NewFile
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import HttpRequest
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _

from jobs.models import Job, JobFile, RunHistory
from jobs.utils import JobAccess, change_job_status, create_job
from reports.models import ReportRoot
from service.models import SolvingProgress
from web.utils import logger, BridgeException, file_checksum
from web.vars import JOB_STATUS, DEFAULT_LAUNCHER_DIR, \
    GENERIC_LAUNCHER_COMMAND, MAX_PROCESSING_JOBS, USER_ROLES, DEFAULT_CONFIGS_DIR, JSON_EXTENSION, \
    VERIFIER_CONFIGURATIONS, PID_FILE

DEFAULT_VERIFIER_DIR = "verifier"
DEFAULT_TASKS_DIR = "tasks"
DEFAULT_BENCHMARK_FILE = "benchmark.xml"


def get_launcher_dir() -> str:
    return os.path.normpath(os.path.join(settings.BASE_DIR, os.pardir, DEFAULT_LAUNCHER_DIR))


class LaunchTask:
    def __init__(self, request: HttpRequest):
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')
        self.launcher_dir = os.path.join(get_launcher_dir(), "results_{}".format(timestamp))
        self.specific_config = None
        self.verifiers = {}
        self.cur_dir = os.getcwd()
        self.error = None
        self.new_job = None
        self.parent = None
        self.user = request.user
        if not self.__is_good():
            return
        data = dict(request.POST)
        for key, val in data.items():
            data[key] = data[key][0]
        self.type = data.get('job_type')
        self.new_job = self.__create_job(data)
        if not self.new_job and not self.parent:
            return
        if not self.__is_benchmark():
            self.__schedule_job()
        os.makedirs(self.launcher_dir)
        self.__process_files(request)
        self.__solve_job(data)

    def __process_files(self, request):
        if request.FILES:
            files_dir = os.path.join(self.launcher_dir, "files")
            os.makedirs(files_dir)
            for file_id in request.FILES:
                for file in request.FILES.getlist(file_id):
                    path = default_storage.save('tmp', ContentFile(file.read()))
                    tmp_file = os.path.join(settings.MEDIA_ROOT, path)
                    stored_file = None
                    if file_id == "upload_config":
                        stored_file = os.path.join(files_dir, "config.json")
                        self.specific_config = stored_file
                    elif file_id == "upload_benchmark_file":
                        stored_file = os.path.join(self.launcher_dir, DEFAULT_BENCHMARK_FILE)
                    elif file_id == "upload_verifier":
                        os.system("unzip {} -d {}".format(tmp_file, os.path.join(self.launcher_dir,
                                                                                 DEFAULT_VERIFIER_DIR)))
                    elif file_id == "upload_tasks":
                        os.system("unzip {} -d {}".format(tmp_file, os.path.join(self.launcher_dir, DEFAULT_TASKS_DIR)))
                    elif str(file_id).startswith('upload_verifier_'):
                        verifier_type = file_id[len('upload_verifier_'):]
                        stored_file = os.path.join(files_dir, verifier_type + ".zip")
                        self.verifiers[verifier_type] = stored_file
                    elif str(file_id).startswith('upload_aux_files_'):
                        dst_file = file_id[len('upload_aux_files_'):]
                        stored_file = os.path.join(files_dir, dst_file)
                    else:
                        logger.warning("Unknown type of uploaded file {}".format(file_id))
                        os.remove(tmp_file)
                        stored_file = None
                    if stored_file:
                        shutil.move(tmp_file, stored_file)
                    else:
                        if os.path.exists(tmp_file):
                            os.remove(tmp_file)

    def __is_benchmark(self):
        if self.type == 'benchmark':
            return True
        else:
            return False

    def __is_good(self) -> bool:
        # check for maximal processed tasks
        number_of_processing_jobs = Job.objects.filter(status=JOB_STATUS[2][0]).count()
        if number_of_processing_jobs > MAX_PROCESSING_JOBS:
            self.error = _('Exceeded max number of processed jobs')
            return False
        # check for user permissions
        if self.user.extended.role not in [USER_ROLES[1][0], USER_ROLES[2][0], USER_ROLES[4][0]]:
            self.error = _('No access')
            return False
        return True

    def __create_job(self, data: dict) -> Optional[Job]:
        parent_job_id = data['parent_job_id']
        new_job_name = data['new_job_name']
        job_desc = data['job_desc']
        try:
            if parent_job_id.isdigit():
                parent_job = Job.objects.get(pk=parent_job_id)
            else:
                parent_job = Job.objects.get(Q(identifier=parent_job_id) | Q(name=parent_job_id))
        except ObjectDoesNotExist:
            self.error = _('Job with specified identifier does not exist')
            return None
        if not JobAccess(self.user, parent_job).can_decide():
            self.error = _('No access')
            return None
        self.parent = parent_job
        if self.__is_benchmark():
            return None
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')
        new_job_name += ' {}'.format(timestamp)
        return create_job({'name': new_job_name, 'author': self.user, 'parent': parent_job, 'description': job_desc,
                           'comment': self.launcher_dir})

    def __schedule_job(self):
        # TODO: Add to pending jobs in case of MAX_PROCESSING_JOBS violated.
        change_job_status(self.new_job, JOB_STATUS[2][0])

    def __solve_job(self, data):
        try:
            os.chdir(self.launcher_dir)
            launcher_env = os.environ.copy()
            if not self.__is_benchmark():
                launcher_env["job_id"] = self.new_job.identifier
            else:
                launcher_env["job_id"] = self.parent.identifier
                launcher_env["job_name"] = data['new_job_name']
            launcher_env["type"] = self.type
            if self.specific_config:
                launcher_env["specific_config"] = self.specific_config
            for verifier_type, arch in self.verifiers.items():
                launcher_env["{}_{}".format("verifier", verifier_type)] = arch
            for key, val in data.items():
                if key:
                    if key == "reuse_tools" and self.verifiers:
                        val = "false"
                    launcher_env[key] = val
            subprocess.run(GENERIC_LAUNCHER_COMMAND, shell=True, check=True, env=launcher_env)
            os.chdir(self.cur_dir)
        except Exception as e:
            logger.exception(e)
            self.error = str(e)


class LauncherData:
    def __init__(self, is_full=False, job_id=None):
        if job_id:
            try:
                job = Job.objects.get(id=job_id)
                is_internal_node = job.status == JOB_STATUS[0][0]
                if is_internal_node:
                    self.parent_job_id = job.id
                    self.new_job_desc = ""
                    self.new_job_name = ""
                else:
                    if job.parent:
                        self.parent_job_id = job.parent.id
                    self.new_job_desc = job.versions.last().description
                    self.new_job_name = job.name
            except ObjectDoesNotExist:
                logger.exception('The job {} does not exist'.format(job_id))
        self.preset_configs = dict()
        launcher_dir = get_launcher_dir()
        configs_dir = os.path.join(launcher_dir, DEFAULT_CONFIGS_DIR)
        for file in glob.glob(os.path.join(configs_dir, "*{}".format(JSON_EXTENSION))):
            file_short = os.path.basename(file)[:-len(JSON_EXTENSION)]
            self.preset_configs[file_short] = ""
            if is_full:
                with open(file) as fd:
                    self.preset_configs[file_short] = fd.read()
        verifier_config = os.path.join(launcher_dir, VERIFIER_CONFIGURATIONS)
        self.verification_tools = list()
        if os.path.exists(verifier_config):
            with open(verifier_config) as fd:
                for line in fd.readlines():
                    property_type, tool, branch, revision = line.rstrip().split(';')
                    self.verification_tools.append((property_type, tool, branch, revision))


class CoreStartDecision:
    def __init__(self, job):
        try:
            progress = SolvingProgress.objects.get(job=job)
        except ObjectDoesNotExist:
            raise ValueError('job decision was not successfully started')
        if progress.start_date is not None:
            raise ValueError('the "start" report of Core was already uploaded')
        elif progress.finish_date is not None:
            raise ValueError('the job is not solving already')
        progress.start_date = now()
        progress.save()


class StopDecision:
    def __init__(self, job):
        if job.status not in [JOB_STATUS[1][0], JOB_STATUS[2][0]]:
            raise BridgeException(_("Only pending and processing jobs can be stopped"))
        try:
            work_dir = job.versions.last().comment
            with open(os.path.join(work_dir, PID_FILE)) as fd:
                pid = fd.read()
            subprocess.run("pkill -P {}".format(pid), shell=True)
            time.sleep(1)
            subprocess.run("kill -9 {}".format(pid), shell=True)
        except Exception as e:
            logger.exception(str(e))

        change_job_status(job, JOB_STATUS[7][0])


class StartJobDecision:
    def __init__(self, user, job_id, configuration, fake=False):
        self.operator = user
        self._fake = fake
        self.configuration = configuration
        self.job = self.__get_job(job_id)

        self.progress = self.__create_solving_progress()
        try:
            ReportRoot.objects.get(job=self.job).delete()
        except ObjectDoesNotExist:
            pass
        ReportRoot.objects.create(user=self.operator, job=self.job)
        self.job.status = JOB_STATUS[1][0]
        self.job.weight = self.configuration.weight
        self.job.save()

    def __get_job(self, job_id):
        try:
            job = Job.objects.get(pk=job_id)
        except ObjectDoesNotExist:
            raise BridgeException(_('The job was not found'))
        if not JobAccess(self.operator, job).can_decide():
            raise BridgeException(_("You don't have an access to start decision of this job"))
        return job

    def __create_solving_progress(self):
        try:
            self.job.solvingprogress.delete()
            self.job.jobprogress.delete()
        except ObjectDoesNotExist:
            pass
        return SolvingProgress.objects.create(
            job=self.job, priority=self.configuration.priority,
            fake=self._fake, configuration=self.__save_configuration()
        )

    def __save_configuration(self):
        m = BytesIO(self.configuration.as_json(self.job.identifier).encode('utf8'))
        check_sum = file_checksum(m)
        try:
            db_file = JobFile.objects.get(hash_sum=check_sum)
        except ObjectDoesNotExist:
            db_file = JobFile(hash_sum=check_sum)
            db_file.file.save('job-%s.conf' % self.job.identifier[:5], NewFile(m), save=True)
        RunHistory.objects.create(job=self.job, operator=self.operator, configuration=db_file, date=now())
        return db_file
