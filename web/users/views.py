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

import pytz
from django.conf import settings
from django.contrib.auth import authenticate, login, logout, models
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned, ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect, JsonResponse, HttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render
from django.urls import reverse
from django.utils.translation import gettext as _, activate

from jobs.models import Job
from marks.models import MarkUnsafeComment
from tools.profiling import unparallel_group
from users.forms import UserExtendedForm, UserForm, EditUserForm
from users.models import Extended, User, View, PreferableView
from users.utils import DEFAULT_VIEW
from web.populate import extend_user
from web.utils import logger
from web.vars import LANGUAGES, UNKNOWN_ERROR, VIEW_TYPES

COLOR_CREATION = "#58bd2a"
COLOR_MODIFICATION = "#582abd"
DEFAULT_ACTIONS_NUMBER = 50


@unparallel_group(['User'])
def user_signin(request):
    activate(request.LANGUAGE_CODE)
    if not isinstance(request.user, models.AnonymousUser):
        logout(request)
    if request.method != 'POST':
        return render(request, 'users/login.html')
    user = authenticate(username=request.POST.get('username'), password=request.POST.get('password'))
    if user is None:
        return render(request, 'users/login.html', {'login_errors': _("Incorrect username or password")})
    if not user.is_active:
        return render(request, 'users/login.html', {'login_errors': _("Account has been disabled")})
    try:
        extended_user = Extended.objects.get(user=user)
        if extended_user.role == '4':
            return render(request, 'users/login.html', {'login_errors': _("Cannot login as a service user")})
        if extended_user.role == '0':
            return render(request, 'users/login.html', {'login_errors': _("You do not have access to loging. "
                                                                          "Please contact the administrator.")})
    except ObjectDoesNotExist:
        extend_user(user)
    login(request, user)
    next_url = request.POST.get('next_url')
    if next_url is not None and next_url != '':
        return HttpResponseRedirect(next_url)
    return HttpResponseRedirect(reverse('jobs:tree'))


def user_signout(request):
    logout(request)
    return HttpResponseRedirect(reverse('users:login'))


def register(request):
    activate(request.LANGUAGE_CODE)
    if not isinstance(request.user, models.AnonymousUser):
        logout(request)

    if request.method == 'POST':
        user_form = UserForm(data=request.POST)
        profile_form = UserExtendedForm(data=request.POST)
        user_tz = request.POST.get('timezone')
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save()
            user.set_password(user.password)
            profile = profile_form.save(commit=False)
            profile.user = user
            if user_tz:
                profile.timezone = user_tz
            try:
                profile.save()
            except:
                raise ValidationError("Can't save user to the database!")
            user.save()
            return HttpResponseRedirect(reverse('users:login'))
    else:
        user_form = UserForm()
        profile_form = UserExtendedForm()

    return render(request, 'users/register.html', {
        'user_form': user_form,
        'profile_form': profile_form,
        'timezones': pytz.common_timezones,
        'def_timezone': settings.DEF_USER['timezone']
    })


@login_required
@unparallel_group([User])
def edit_profile(request):
    activate(request.user.extended.language)

    if request.method == 'POST':
        user_form = EditUserForm(data=request.POST, request=request, instance=request.user)
        profile_form = UserExtendedForm(data=request.POST, instance=request.user.extended)
        user_tz = request.POST.get('timezone')
        if user_form.is_valid() and profile_form.is_valid():
            user = user_form.save(commit=False)
            new_pass = request.POST.get('new_password')
            do_redirect = False
            if len(new_pass) > 0:
                user.set_password(new_pass)
                do_redirect = True
            user.save()
            profile = profile_form.save(commit=False)
            profile.user = user
            if user_tz:
                profile.timezone = user_tz
            profile.save()

            if do_redirect:
                return HttpResponseRedirect(reverse('users:login'))
            else:
                return HttpResponseRedirect(reverse('users:edit_profile'))
        else:
            logger.error(f"Can't update user data due to: {user_form.errors or profile_form.errors}")
    else:
        user_form = EditUserForm(instance=request.user)
        profile_form = UserExtendedForm(instance=request.user.extended)

    return render(
        request,
        'users/edit-profile.html',
        {
            'user_form': user_form,
            'tdata': "",
            'profile_form': profile_form,
            'profile_errors': profile_form.errors,
            'user_errors': user_form.errors,
            'timezones': pytz.common_timezones,
            'LANGUAGES': LANGUAGES
        })


@login_required
@unparallel_group([])
def show_profile(request, user_id):
    activate(request.user.extended.language)
    actions_number = int(request.GET.get('actions', DEFAULT_ACTIONS_NUMBER))
    actions_number_partial = round(actions_number / 1.5)
    try:
        target = User.objects.get(pk=user_id)
    except ObjectDoesNotExist:
        return render(request, 'users/showProfile.html', {
            'error': _("Required object does not exist")})
    user_role = Extended.objects.get(user=request.user).role
    if not user_role == '2' and not target == request.user:
        return render(request, 'users/showProfile.html', {
            'error': _("You don't have an access to this page")})

    from jobs.models import JobHistory
    from jobs.utils import JobAccess
    from marks.models import MarkSafeHistory, MarkUnsafeHistory, MarkUnknownHistory

    activity = []
    for act in JobHistory.objects.filter(change_author=target).order_by('-change_date')[:actions_number_partial]:
        act_comment = act.comment
        small_comment = act_comment
        if len(act_comment) > 50:
            small_comment = act_comment[:47] + '...'
        if act.version == 1:
            act_type = _('Creation')
            act_color = COLOR_CREATION
        else:
            act_type = _('Modification')
            act_color = COLOR_MODIFICATION
        new_act = {
            'date': act.change_date,
            'comment': act_comment,
            'small_comment': small_comment,
            'act_type': act_type,
            'act_color': act_color,
            'obj_type': _('Job'),
            'obj_link': act.job.name
        }
        if JobAccess(request.user, act.job).can_view():
            new_act['href'] = reverse('jobs:job', args=[act.job_id])
        activity.append(new_act)
    for act in MarkSafeHistory.objects.filter(author=target).order_by('-change_date')[:actions_number_partial]:
        act_comment = act.comment
        small_comment = act_comment
        if len(act_comment) > 50:
            small_comment = act_comment[:47] + '...'
        if act.version == 1:
            act_type = _('Creation')
            act_color = COLOR_CREATION
        else:
            act_type = _('Modification')
            act_color = COLOR_MODIFICATION
        activity.append({
            'date': act.change_date,
            'comment': act_comment,
            'small_comment': small_comment,
            'act_type': act_type,
            'act_color': act_color,
            'obj_type': _('Safes mark'),
            'obj_link': act.mark.identifier,
            'href': reverse('marks:mark', args=['safe', act.mark_id]),
        })
    for act in MarkUnsafeHistory.objects.filter(author=target).order_by('-change_date')[:actions_number_partial]:
        act_comment = act.comment
        small_comment = act_comment
        if len(act_comment) > 47:
            small_comment = act_comment[:50] + '...'
        if act.version == 1:
            act_type = _('Creation')
            act_color = COLOR_CREATION
        else:
            act_type = _('Modification')
            act_color = COLOR_MODIFICATION
        activity.append({
            'date': act.change_date,
            'comment': act_comment,
            'small_comment': small_comment,
            'act_type': act_type,
            'act_color': act_color,
            'obj_type': _('Unsafes mark'),
            'obj_link': act.mark.identifier,
            'href': reverse('marks:mark', args=['unsafe', act.mark_id])
        })
    for act in MarkUnknownHistory.objects.filter(author=target).order_by('-change_date')[:actions_number_partial]:
        act_comment = act.comment
        small_comment = act_comment
        if len(act_comment) > 50:
            small_comment = act_comment[:47] + '...'
        if act.version == 1:
            act_type = _('Creation')
            act_color = COLOR_CREATION
        else:
            act_type = _('Modification')
            act_color = COLOR_MODIFICATION
        activity.append({
            'date': act.change_date,
            'comment': act_comment,
            'small_comment': small_comment,
            'act_type': act_type,
            'act_color': act_color,
            'obj_type': _('Unknowns mark'),
            'obj_link': act.mark.identifier,
            'href': reverse('marks:mark', args=['unknown', act.mark_id])
        })
    return render(request, 'users/showProfile.html', {
        'target': target,
        'activity': list(reversed(sorted(activity, key=lambda x: x['date'])))[:actions_number],
    })


@login_required
@unparallel_group([])
def show_comments(request):
    activate(request.user.extended.language)
    all_comments = []
    try:
        all_comments = MarkUnsafeComment.objects.order_by('-date')
    except:
        JsonResponse({'error': 'Comments were not found'})

    return render(request, 'users/showComments.html', {
        'comments': all_comments,
    })


@unparallel_group(['User'])
def service_signin(request):
    if request.method != 'POST':
        get_token(request)
        return HttpResponse('')
    username = request.POST.get('username')
    password = request.POST.get('password')
    for p in request.POST:
        if p == 'job identifier':
            try:
                request.session['job id'] = Job.objects.get(identifier__startswith=request.POST[p]).pk
            except ObjectDoesNotExist:
                return JsonResponse({
                    'error': 'The job with specified identifier "%s" was not found' % request.POST[p]
                })
            except MultipleObjectsReturned:
                return JsonResponse({'error': 'The specified job identifier is not unique'})

    user = authenticate(username=username, password=password)
    if user is None:
        return JsonResponse({'error': 'Incorrect username or password'})
    if not user.is_active:
        return JsonResponse({'error': 'Account has been disabled'})
    try:
        Extended.objects.get(user=user)
    except ObjectDoesNotExist:
        return JsonResponse({'error': 'User does not have extended data'})
    login(request, user)
    return HttpResponse('')


@unparallel_group([])
def service_signout(request):
    logout(request)
    return HttpResponse('')


@unparallel_group([PreferableView, 'View'])
def preferable_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    view_id = request.POST.get('view_id', None)
    view_type = request.POST.get('view_type', None)
    if view_id is None or view_type is None or view_type not in set(x[0] for x in VIEW_TYPES):
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    if view_id == 'default':
        pref_views = request.user.preferableview_set.filter(view__type=view_type)
        if len(pref_views):
            pref_views.delete()
            return JsonResponse({'message': _("The default view was made preferred")})
        return JsonResponse({'error': _("The default view is already preferred")})

    try:
        user_view = View.objects.get(Q(id=view_id, type=view_type) & (Q(author=request.user) | Q(shared=True)))
    except ObjectDoesNotExist:
        return JsonResponse({'error': _("The view was not found")})
    request.user.preferableview_set.filter(view__type=view_type).delete()
    PreferableView.objects.create(user=request.user, view=user_view)
    return JsonResponse({'message': _("The preferred view was successfully changed")})


@unparallel_group([PreferableView, 'View'])
def get_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    view_id = request.POST.get('view_id', None)
    view_type = request.POST.get('view_type', None)
    if view_id is None or view_type is None or view_type not in set(x[0] for x in VIEW_TYPES):
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    if view_id == 'default':
        columns = DEFAULT_VIEW[view_type].get('columns')
    else:
        try:
            user_view = View.objects.get(Q(id=view_id, type=view_type) & (Q(author=request.user) | Q(shared=True)))
            columns = json.loads(user_view.view).get('columns')
        except ObjectDoesNotExist:
            return JsonResponse({'error': _("The view was not found")})
    return JsonResponse({'columns': columns})


@unparallel_group(['View'])
def check_view_name(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    view_name = request.POST.get('view_title', None)
    view_type = request.POST.get('view_type', None)
    if view_name is None or view_type is None:
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    if view_name == '':
        return JsonResponse({'error': _("The view name is required")})

    if view_name == str(_('Default')) or request.user.view_set.filter(type=view_type, name=view_name).count():
        return JsonResponse({'error': _("Please choose another view name")})
    return JsonResponse({})


@unparallel_group([View])
def save_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    view_data = request.POST.get('view', None)
    view_name = request.POST.get('title', '')
    view_id = request.POST.get('view_id', None)
    view_type = request.POST.get('view_type', None)
    if view_data is None or view_type is None or view_type not in list(x[0] for x in VIEW_TYPES):
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    if view_id == 'default':
        return JsonResponse({'error': _("You can't edit the default view")})
    elif view_id is not None:
        try:
            new_view = request.user.view_set.get(pk=int(view_id))
        except ObjectDoesNotExist:
            return JsonResponse({'error': _("The view was not found or you don't have an access to it")})
    elif len(view_name) > 0:
        new_view = View(name=view_name, type=view_type, author=request.user)
    else:
        return JsonResponse({'error': _('The view name is required')})
    new_view.view = view_data
    new_view.save()
    return JsonResponse({
        'view_id': new_view.id, 'view_name': new_view.name,
        'message': _("The view was successfully saved")
    })


@unparallel_group([View])
def remove_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': str(UNKNOWN_ERROR)})

    v_id = request.POST.get('view_id', 0)
    view_type = request.POST.get('view_type', None)
    if view_type is None:
        return JsonResponse({'error': str(UNKNOWN_ERROR)})
    if v_id == 'default':
        return JsonResponse({'error': _("You can't remove the default view")})
    try:
        View.objects.get(id=v_id, author=request.user, type=view_type).delete()
    except ObjectDoesNotExist:
        return JsonResponse({'error': _("The view was not found or you don't have an access to it")})
    return JsonResponse({'message': _("The view was successfully removed")})


@unparallel_group([View])
def share_view(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': _('You are not signing in')})
    activate(request.user.extended.language)

    if request.method != 'POST':
        return JsonResponse({'error': 'Unknown error'})

    v_id = request.POST.get('view_id', 0)
    view_type = request.POST.get('view_type', None)
    if view_type is None:
        return JsonResponse({'error': 'Unknown error'})
    if v_id == 'default':
        return JsonResponse({'error': _("You can't share the default view")})
    try:
        view = View.objects.get(author=request.user, pk=v_id, type=view_type)
    except ObjectDoesNotExist:
        return JsonResponse({'error': _("The view was not found or you don't have an access to it")})
    view.shared = not view.shared
    view.save()
    if view.shared:
        return JsonResponse({'message': _("The view was successfully shared")})
    PreferableView.objects.filter(view=view).exclude(user=request.user).delete()
    return JsonResponse({'message': _("The view was hidden from other users")})
