/*
 * CVV is a continuous verification visualizer.
 * Copyright (c) 2023 ISP RAS (http://www.ispras.ru)
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

function clear_reply_form(mark_id) {
    let previous_comment = document.getElementById('edit_comment_id_' + mark_id);
    if (previous_comment.value) {
        document.getElementById("comment_text_" + previous_comment.value).style.background = "#ffffff";
    }
    previous_comment.value = "";
}

function show_comments(mark_id) {
    $('.comment.collapsed').each(function () { !$(this).toggleClass("collapsed")});
    $('#show_comments_btn_' + mark_id).modal('hide');
}

function reply_comment(comment_id, username, mark_id) {
    const orig_text = document.getElementById("comment_text_" + comment_id).innerHTML;
    document.getElementById('new_comment_field_' + mark_id).value = username + ":<blockquote>" + orig_text + "</blockquote>\n";
    $("#new_comment_field_" + mark_id).focus();
    clear_reply_form(mark_id);
}

function edit_comment(comment_id, mark_id) {
    const orig_text = document.getElementById("comment_text_" + comment_id).innerHTML;
    document.getElementById('new_comment_field_' + mark_id).value = orig_text;
    $("#new_comment_field_" + mark_id).focus();
    clear_reply_form(mark_id);
    document.getElementById('edit_comment_id_' + mark_id).value = comment_id;
    document.getElementById("comment_text_" + comment_id).style.background = "#f9f9f9";
}

function new_comment(mark_id) {
    let comment_id = document.getElementById('edit_comment_id_' + mark_id).value;
    var desc = $('#new_comment_field_' + mark_id).val();
    if (!desc) {
        return;
    }
    const root_comment = $('#comments_root_' + mark_id);
    const report_id = $('#report_pk').val();

    var cmt_data = {
        description: desc, mark_id: mark_id, comment_id: comment_id, report_id: report_id
    };

    $.post('/marks/create-comment/', cmt_data, function (data) {
        if (data.error) {
            err_notify(data.error);
            return false;
        }
        if (comment_id) {
            // Edit comment
            document.getElementById("comment_text_" + comment_id).innerHTML = desc;
        } else {
            // New comment
            const user_name = data['user_name'];
            const user_id = data['user_id'];
            comment_id = data['comment_id'];
            let new_comment = document.createElement('div');
            new_comment.className = 'comment';
            new_comment.innerHTML = `
            <div id="comment_${comment_id}" class="content">
                <a href="/users/profile/${user_id}" class="author">${user_name}</a>
                <div class="metadata">
                    <span class="date">Now</span>
                </div>
                <div id="comment_text_${comment_id}" class="text">${desc}</div>
                <div class="actions">
                    <a class="reply" onclick="reply_comment('${comment_id}', '${user_name}', '${mark_id}')">Reply</a>
                    <a class="edit" onclick="edit_comment(${comment_id}, ${mark_id})">Edit</a>
                    <a class="delete" onclick="delete_comment(${comment_id}, ${mark_id})">Delete</a>
                </div>
            </div>`;
            root_comment.prepend(new_comment);
        }
        clear_reply_form(mark_id);
        document.getElementById('new_comment_field_' + mark_id).value = "";
    });
}

function delete_comment(comment_id, mark_id) {
    var cmt_data = {
        comment_id: comment_id
    };
    $.post('/marks/delete-comment/', cmt_data, function (data) {
        if (data.error) {
            err_notify(data.error);
            return false;
        }
        clear_reply_form(mark_id);
        let removed_comment = document.getElementById("comment_" + comment_id);
        removed_comment.parentNode.removeChild(removed_comment);
    });
}

function review_mark(mark_id) {
    let removed_button = document.getElementById("review_" + mark_id);
    removed_button.setAttribute('disabled', '');
    const report_id = $('#report_pk').val();
    var review_data = {
        report_id: report_id, mark_id: mark_id
    };
    $.post('/marks/submit-review/', review_data, function (data) {
        if (data.error) {
            err_notify(data.error);
            return false;
        }
    });
}

function delete_review(mark_id) {
    let removed_button = document.getElementById("delete_review_" + mark_id);
    removed_button.setAttribute('disabled', '');
    const report_id = $('#report_pk').val();
    var review_data = {
        report_id: report_id, mark_id: mark_id
    };
    $.post('/marks/delete-review/', review_data, function (data) {
        if (data.error) {
            err_notify(data.error);
            return false;
        }
    });
}
