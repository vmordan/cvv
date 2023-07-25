/*
 * CVV is a continuous verification visualizer.
 * Copyright (c) 2023 ISP RAS (http://www.ispras.ru)
 * Ivannikov Institute for System Programming of the Russian Academy of Sciences
 *
 * Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
 * Ivannikov Institute for System Programming of the Russian Academy of Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * ee the License for the specific language governing permissions and
 * limitations under the License.
 */

function error_or_reload(data) {
    $('#dimmer_of_page').removeClass('active');
    data.error ? err_notify(data.error) : window.location.replace('')
}

function check_status(interval) {
    $.post(
        '/jobs/status/' + $('#job_id').val() + '/',
        {},
        function (data) {
            if (data.error) {
                err_notify(data.error);
                clearInterval(interval);
            }
            else if (data.status != $('#job_status_value').val()) {
                window.location.replace('');
            }
        }
    ).fail(function () {
        clearInterval(interval);
    });
}

function activate_download_for_compet() {
    var dfc_modal = $('#dfc_modal');
    dfc_modal.modal({transition: 'slide down', autofocus: false, closable: false});
    $('#dfc_modal_show').click(function () {
        if ($(this).hasClass('disabled')) return false;
        $('.browse').popup('hide');
        dfc_modal.modal('show');
    });
    dfc_modal.find('.ui.checkbox').checkbox();
    $('#dfc__f').parent().checkbox({
        onChecked: function () {
            $('#dfc_problems').show();
        },
        onUnchecked: function () {
            $('#dfc_problems').hide();
        }
    });
    $('#dfc__cancel').click(function () {
        $('#dfc_modal').modal('hide');
    });
    $('#dfc__confirm').click(function () {
        var svcomp_filters = [];
        if ($('#dfc__u').parent().checkbox('is checked')) {
            svcomp_filters.push('u');
        }
        if ($('#dfc__s').parent().checkbox('is checked')) {
            svcomp_filters.push('s');
        }
        if ($('#dfc__f').parent().checkbox('is checked')) {
            var unknowns_filters = [];
            $('input[id^="dfc__p__"]').each(function () {
                if ($(this).parent().checkbox('is checked')) {
                    unknowns_filters.push($(this).val());
                }
            });
            svcomp_filters.push(unknowns_filters);
        }
        if (svcomp_filters.length == 0) {
            err_notify($('#error___dfc_notype').text());
        }
        else {
            $('#dfc_modal').modal('hide');
            $.redirectPost('/jobs/downloadcompetfile/' + $('#job_id').val() + '/', {'filters': JSON.stringify(svcomp_filters)});
        }
    });

}

function activate_run_history() {
    $('#run_history').dropdown();
    var download_conf_btn = $('#download_configuration');
    download_conf_btn.popup();
    download_conf_btn.click(function () {
        window.location.replace('/jobs/download_configuration/' + $('#run_history').val() + '/');
    });
}

function show_warn_modal(btn, warn_text_id, action_func, disabled) {
    disabled = typeof disabled !== 'undefined' ?  disabled : btn.hasClass('disabled');
    if (disabled) return false;
    $('.browse').popup('hide');

    var warn_confirm_btn = $('#warn_confirm_btn');
    $('#warn_text').text($('#' + warn_text_id).text());
    warn_confirm_btn.unbind();
    warn_confirm_btn.click(function () {
        $('#warn_modal').modal('hide');
        action_func();
    });
    $('#warn_modal').modal('show');
}

function remove_job() {
    $('#dimmer_of_page').addClass('active');
    $.post(
        '/jobs/remove/',
        {jobs: JSON.stringify([$('#job_id').val()])},
        function (data) {
            $('#dimmer_of_page').removeClass('active');
            data.error ? err_notify(data.error) : window.location.replace('/jobs/');
        }, 'json'
    );
}

function clear_job() {
    $('#dimmer_of_page').addClass('active');
    $.post(
        '/jobs/clear/',
        {jobs: JSON.stringify([$('#job_id').val()])},
        function (data) {
            $('#dimmer_of_page').removeClass('active');
            data.error ? err_notify(data.error) : window.location.replace('/jobs/' + $('#job_id').val());
        }, 'json'
    );
}

function check_children() {
    $.post('/jobs/do_job_has_children/' + $('#job_id').val() + '/', {}, function (data) {
        if (data.error) {
            err_notify(data.error);
            return false;
        }
        data.children ? show_warn_modal(null, 'warn__has_children', remove_job, false) : remove_job();
    }, 'json');
}

function fast_run_decision() {
    $('#dimmer_of_page').addClass('active');
    $.post('/jobs/run_decision/' + $('#job_id').val() + '/', {mode: 'fast'}, error_or_reload);
}

function lastconf_run_decision() {
    $('#dimmer_of_page').addClass('active');
    $.post('/jobs/run_decision/' + $('#job_id').val() + '/', {mode: 'lastconf'}, error_or_reload);
}

function stop_job_decision() {
    $('#dimmer_of_page').addClass('active');
    $.post('/jobs/stop_decision/' + $('#job_id').val() + '/', {}, error_or_reload);
}

function collapse_reports() {
    $('#dimmer_of_page').addClass('active');
    $.post('/jobs/collapse_reports/' + $('#job_id').val() + '/', {}, error_or_reload);
}

function clear_verification_files() {
    $('#dimmer_of_page').addClass('active');
    $.post('/reports/clear_verification_files/' + $('#job_id').val() + '/', {}, error_or_reload);
}

function get_attrs() {
    var elems = $('input:checkbox');
    var attrs = {};
    for (var elem in elems) {
        if (elems[elem].id && elems[elem].checked && elems[elem].id.startsWith('attr_')) {
            attrs[elems[elem].id] = elems[elem].value;
        }
    }
    $.post('/jobs/set_attrs/' + $('#job_id').val() + '/', {'data': JSON.stringify(attrs)},
        function (data) {
            $('#apply_attributes').removeClass('disabled');
            if (data.error) {
                err_notify(data.error);
                return false;
            }
            if (data.is_reload) {
                window.location.replace('');
            }
        }
    );
}

$(document).ready(function () {
    $('.ui.dropdown').dropdown();
    $('#resources-note').popup();
    $('.menu-link').click(function (event) {
        if ($(this).hasClass('disabled')) {
            event.preventDefault();
            return false;
        }
        return true;
    });

    activate_download_for_compet();
    activate_run_history();
    init_versions_list();

    $('#warn_modal').modal({transition: 'fade in', autofocus: false, closable: false});
    $('#warn_close_btn').click(function () { $('#warn_modal').modal('hide') });
    $('#remove_job_btn').click(function () { show_warn_modal($(this), 'warn__remove_job', check_children) });
    $('#clear_job_btn').click(function () { show_warn_modal($(this), 'warn__clear_job', clear_job) });
    $('#decide_job_btn').click(function () { show_warn_modal($(this), 'warn__decide_job', function () { window.location.href = '/jobs/prepare_run/' + $('#job_id').val() + '/' }) });
    $('#fast_decide_job_btn').click(function () { show_warn_modal($(this), 'warn__decide_job', fast_run_decision) });
    $('#last_decide_job_btn').click(function () { show_warn_modal($(this), 'warn__decide_job', lastconf_run_decision) });
    $('#stop_job_btn').click(function () { show_warn_modal($(this), 'warn__stop_decision', stop_job_decision) });
    $('#collapse_reports_btn').click(function () { show_warn_modal($(this), 'warn__collapse', collapse_reports) });
    $('#clear_verifications_modal').click(function () { show_warn_modal($(this), 'warn__clear_files', clear_verification_files) });

    var job_status_popup = $('#job_status_popup');
    if (job_status_popup.length) $('#job_status_popup_activator').popup({popup: job_status_popup, position: 'bottom center'});

    $('#download_job_btn').click(function () {
        if ($(this).hasClass('disabled')) return false;
        $('.browse').popup('hide');
        return true;
    });

    $('#upload_reports_popup').modal({transition: 'vertical flip'});
    $('#upload_reports_btn').click(function () {
        if ($(this).hasClass('disabled')) return false;
        $('.browse').popup('hide');
        $('#upload_reports_popup').modal('show');
    });
    $('#upload_reports_file_input').on('fileselect', function () {
        $('#upload_reports_filename').html($('<span>', {text: $(this)[0].files[0].name}));
    });
    $('#upload_reports_cancel').click(function () {
        var file_input = $('#upload_reports_file_input');
        file_input.replaceWith(file_input.clone( true ));
        $('#upload_reports_filename').empty();
        $('#upload_reports_popup').modal('hide');
    });
    $('#apply_attributes').click(function () {
        $(this).addClass('disabled');
        get_attrs();
    });
    $('#cancel_attributes').click(function () {
        $(this).addClass('disabled');
        $.post('/jobs/set_attrs/' + $('#job_id').val() + '/', {'data': {}}, error_or_reload);
    });
    $('#upload_reports_start').click(function () {
        var files = $('#upload_reports_file_input')[0].files,
            data = new FormData();
        if (files.length <= 0) {
            err_notify($('#error__no_file_chosen').text());
            return false;
        }
        data.append('archive', files[0]);
        $('#upload_reports_popup').modal('hide');
        $('#dimmer_of_page').addClass('active');
        $.ajax({
            url: '/jobs/upload_reports/' + $('#job_id').val() + '/',
            type: 'POST',
            data: data,
            dataType: 'json',
            contentType: false,
            processData: false,
            mimeType: 'multipart/form-data',
            xhr: function() { return $.ajaxSettings.xhr() },
            success: function (data) {
                $('#dimmer_of_page').removeClass('active');
                data.error ? err_notify(data.error) : window.location.replace('');
            }
        });
        return false;
    });
});

function show_resource_table_body() {
    $('#resource_table_body').toggle();
}
