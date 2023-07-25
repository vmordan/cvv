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

import json
import os

from django.conf import settings
from django.db.models import Q
from django.test import Client
from django.urls import reverse

from jobs.models import Job
from reports.test import COMPUTER
from service.models import SolvingProgress, Task, Solution
from users.models import User
from web.populate import populate_users
from web.utils import CVTestCase
from web.vars import JOB_STATUS, PRIORITY

TEST_JSON = {
    'tasks': {
        'pending': [],
        'processing': [],
        'finished': [],
        'error': []
    },
    'task errors': {},
    'task descriptions': {},
    'task solutions': {},
    'jobs': {
        'pending': [],
        'processing': [],
        'finished': [],
        'error': [],
        'cancelled': []
    },
    'job errors': {},
    'job configurations': {}
}

ARCHIVE_PATH = os.path.join(settings.BASE_DIR, 'service', 'test_files')


class TestService(CVTestCase):
    def setUp(self):
        super(TestService, self).setUp()
        User.objects.create_superuser('superuser', '', 'top_secret')
        populate_users(
            manager={'username': 'manager', 'password': 'manager'},
            service={'username': 'service', 'password': 'service'}
        )
        self.client.post(reverse('users:login'), {'username': 'manager', 'password': 'manager'})
        self.client.post(reverse('population'))
        self.controller = Client()
        self.controller.post('/users/service_signin/', {'username': 'service', 'password': 'service'})
        try:
            self.job = Job.objects.filter(~Q(parent=None))[0]
        except IndexError:
            self.job = Job.objects.all()[0]
        # Run decision
        self.client.post('/jobs/run_decision/%s/' % self.job.pk, {'mode': 'default', 'conf_name': 'development'})
        self.core = Client()
        self.core.post('/users/service_signin/', {
            'username': 'service', 'password': 'service', 'job identifier': self.job.identifier
        })

    def test1_success(self):
        # Decide the job
        response = self.core.post('/jobs/decide_job/', {'report': json.dumps({
            'type': 'start', 'id': '/', 'comp': COMPUTER,
            'attrs': [{'name': 'Core version', 'value': 'stage-2-1k123j13'}]
        }), 'job format': 1})
        self.assertEqual(response.status_code, 200)
        self.assertIn(response['Content-Type'], {'application/x-zip-compressed', 'application/zip'})
        self.assertEqual(Job.objects.get(pk=self.job.pk).status, JOB_STATUS[2][0])

        # Upload finish report
        with open(os.path.join(settings.BASE_DIR, 'reports', 'test_files', 'log.zip'), mode='rb') as fp:
            response = self.core.post('/reports/upload/', {
                'report': json.dumps({
                    'id': '/', 'type': 'finish', 'resources': {
                        'CPU time': 1000, 'memory size': 5 * 10 ** 8, 'wall time': 2000
                    },
                    'log': 'log.zip', 'desc': 'It does not matter'
                }), 'file': fp
            })
            fp.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))

        # Status is corrupted beacause there are unfinisheed tasks
        self.assertEqual(Job.objects.get(pk=self.job.pk).status, JOB_STATUS[3][0])

        # Check tasks quantities after finishing job decision
        progress = SolvingProgress.objects.get(job_id=self.job.pk)
        self.assertEqual(progress.tasks_total, 5)
        self.assertEqual(progress.solutions, 2)
        self.assertEqual(progress.tasks_error, 1)
        self.assertEqual(progress.tasks_processing, 0)
        self.assertEqual(progress.tasks_pending, 0)
        self.assertEqual(progress.tasks_finished, 2)
        self.assertEqual(progress.tasks_cancelled, 2)

    def test2_unfinished_tasks(self):
        sch_data = {
            'tasks': {'pending': [], 'processing': [], 'error': [], 'finished': [], 'cancelled': []},
            'task errors': {}, 'task descriptions': {}, 'task solutions': {},
            'jobs': {'pending': [], 'processing': [], 'error': [], 'finished': [], 'cancelled': []},
            'job errors': {}, 'job configurations': {}
        }
        # Decide the job
        self.core.post('/jobs/decide_job/', {'report': json.dumps({
            'type': 'start', 'id': '/', 'comp': COMPUTER,
            'attrs': [{'name': 'Core version', 'value': 'stage-2-1k123j13'}]
        }), 'job format': 1})
        self.assertEqual(Job.objects.get(pk=self.job.pk).status, JOB_STATUS[2][0])

        # Schedule 5 tasks
        task_ids = []
        for i in range(0, 5):
            with open(os.path.join(ARCHIVE_PATH, 'archive.zip'), mode='rb') as fp:
                response = self.core.post('/service/schedule_task/', {
                    'description': json.dumps({'priority': PRIORITY[3][0]}), 'file': fp
                })
                fp.close()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'application/json')
            self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))
            self.assertEqual(len(Task.objects.filter(progress__job_id=self.job.pk)), 1 + i)
            task_id = json.loads(str(response.content, encoding='utf8')).get('task id', 0)
            self.assertEqual(len(Task.objects.filter(pk=task_id)), 1)
            task_ids.append(str(task_id))
        progress = SolvingProgress.objects.get(job_id=self.job.pk)
        self.assertEqual(progress.tasks_pending, 5)
        self.assertEqual(progress.tasks_total, 5)

        # Cancel the 4th task
        self.core.post('/service/cancel_task/', {'task id': task_ids[3]})
        self.assertEqual(len(Task.objects.filter(pk=task_ids[3])), 0)
        progress = SolvingProgress.objects.get(job_id=self.job.pk)
        self.assertEqual(progress.tasks_total, 5)
        self.assertEqual(progress.tasks_pending, 1)
        self.assertEqual(progress.tasks_processing, 3)
        self.assertEqual(progress.tasks_cancelled, 1)

        # Upload solution for the 1st task
        with open(os.path.join(ARCHIVE_PATH, 'archive.zip'), mode='rb') as fp:
            response = self.core.post('/service/upload_solution/', {
                'task id': task_ids[0], 'file': fp, 'description': json.dumps({'resources': {'wall time': 1000}})
            })
            fp.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))
        self.assertEqual(len(Solution.objects.filter(task_id=task_ids[0])), 1)
        self.assertEqual(SolvingProgress.objects.get(job_id=self.job.pk).solutions, 1)

        # Delete finished tasks (FAIL FOR WINDOWS)
        response = self.core.post('/service/remove_task/', {'task id': task_ids[0]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))
        response = self.core.post('/service/remove_task/', {'task id': task_ids[1]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))
        self.assertEqual(len(Task.objects.filter(id__in=[task_ids[0], task_ids[1], task_ids[3]])), 0)

        # Upload finish report
        with open(os.path.join(settings.BASE_DIR, 'reports', 'test_files', 'log.zip'), mode='rb') as fp:
            response = self.core.post('/reports/upload/', {
                'report': json.dumps({
                    'id': '/', 'type': 'finish', 'resources': {
                        'CPU time': 1000, 'memory size': 5 * 10 ** 8, 'wall time': 2000
                    },
                    'log': 'log.zip', 'desc': 'It does not matter'
                }), 'file': fp
            })
            fp.close()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertNotIn('error', json.loads(str(response.content, encoding='utf8')))

        # Status is corrupted because there are unfinished tasks
        self.assertEqual(Job.objects.get(pk=self.job.pk).status, JOB_STATUS[5][0])

        # Check tasks quantities after finishing job decision
        progress = SolvingProgress.objects.get(job_id=self.job.pk)
        self.assertEqual(progress.tasks_total, 5)
        self.assertEqual(progress.solutions, 1)
        self.assertEqual(progress.tasks_error, 1)
        self.assertEqual(progress.tasks_processing, 1)
        self.assertEqual(progress.tasks_pending, 1)
        self.assertEqual(progress.tasks_finished, 1)
        self.assertEqual(progress.tasks_cancelled, 1)
