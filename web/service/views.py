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

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.translation import activate

import service.utils
from web.vars import USER_ROLES


@login_required
def launcher_view(request, pk=""):
    if request.user.extended.role not in [USER_ROLES[1][0], USER_ROLES[2][0], USER_ROLES[4][0]]:
        return JsonResponse({'error': 'No access'})
    activate(request.user.extended.language)
    return render(request, 'service/launcher.html', {'data': service.utils.LauncherData(job_id=pk)})


@login_required
def launch_job(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST requests are supported'})
    launcher = service.utils.LaunchTask(request)
    if launcher.new_job:
        return JsonResponse({'new_job_id': launcher.new_job.id})
    elif launcher.parent:
        return JsonResponse({'new_job_id': launcher.parent.id})
    else:
        return JsonResponse({'error': launcher.error})
