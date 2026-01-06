// For Ticket Status Updates

function closeTicket(ticketId) {
    fetch("/close-ticket", {
        method: "POST",
        body: JSON.stringify({ ticketId: ticketId }),
        headers: { "Content-Type": "application/json" },
    }).then((_res) => {
        // Wait a bit then reload page so new status is shown
        setTimeout(() => window.location.reload(), 200);
    });
}

function solveTicket(ticketId) {
    fetch("/solve-ticket", {
        method: "POST",
        body: JSON.stringify({ ticketId: ticketId }),
        headers: { "Content-Type": "application/json" },
    }).then((_res) => {
        // Wait a bit then reload page so new status is shown
        setTimeout(() => window.location.reload(), 200);
    });
}

// Update Ticket Priority (from user dashboard)
function updateTicketPriority(selectElement) {
    const ticketId = selectElement.dataset.ticketId;
    const newPriority = selectElement.value;

    // Visually indicate processing by disabling the dropdown
    $(selectElement).prop('disabled', true);

    fetch(`/update-ticket-priority/${ticketId}`, {
        method: 'POST',
        body: JSON.stringify({ priority: newPriority }),
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('success', `✅ Priority updated to ${newPriority}`);
        } else {
            showToast('error', `❌ Error: ${data.error || 'Could not update priority'}`);
        }
    }).catch(() => {
        showToast('error', '❌ Network error. Could not update priority.');
    }).finally(() => $(selectElement).prop('disabled', false)); // Always re-enable the dropdown
}

// Update Ticket ETA (from admin dashboard table)
function updateTicketETA(selectElement) {
    const ticketId = selectElement.dataset.ticketId;
    const newETA = selectElement.value;

    // Visually indicate processing
    $(selectElement).prop('disabled', true);

    fetch(`/update-ticket-eta/${ticketId}`, {
        method: 'POST',
        body: JSON.stringify({ eta: newETA }),
        headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        },
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('success', `✅ ETA updated for ticket #${ticketId}`);
        } else {
            showToast('error', `❌ Error: ${data.error || 'Could not update ETA'}`);
        }
    }).finally(() => $(selectElement).prop('disabled', false));
}
// Zoom Accessibility

// Global utility function for formatting UTC dates to local time
function server_local_format(utc_string, format = '%d-%m-%Y %H:%M') {
    if (!utc_string) return 'N/A';
    try {
        const date = new Date(utc_string);
        if (isNaN(date)) return utc_string;

        // A simple formatter, not as robust as a library but works for this case
        const day = String(date.getDate()).padStart(2, '0');
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const year = date.getFullYear();
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');

        if (format === '%d-%m-%Y %H:%M') {
            return `${day}-${month}-${year} ${hours}:${minutes}`;
        }
        // Add more formats if needed
        return date.toLocaleString();
    } catch (e) {
        return utc_string;
    }
}

// Global function to populate the View Ticket Modal (used by admin_dashboard.html)
function populateViewTicketModal(data) {
    $("#view-ticket-title").val(data.title);
    $("#view-ticket-project").val(data.project);
    $("#view-ticket-created-by").val(data.created_by);
    $("#view-ticket-created-on").val(server_local_format(data.date));
    $("#view-ticket-team-lead").val(data.project_manager);
    $("#view-ticket-location").val(data.location);
    $("#view-ticket-cubical").val(data.cubical);
    $("#view-ticket-type").val(data.ticket_type);
    $("#view-ticket-desc").val(data.desc);
    $("#view-ticket-category").val(data.category);
    $("#view-ticket-priority").val(data.priority);
    $("#view-assign-user").val(data.assigned);
    $("#view-assign-status").val(data.status);

    if (data.movement_from || data.movement_to) {
        $("#view-movement-from").val(data.movement_from);
        $("#view-movement-to").val(data.movement_to);
        $("#view-movement-fields").show();
    } else {
        $("#view-movement-fields").hide();
    }

    loadCommentHistory(data.id, '#view-modal-comment-history');
}

$(document).on('click', '.view-ticket-btn', function () {
    const ticketId = $(this).data('ticket-id');
    const modal = $('#viewTicketModal');
    const modalBody = modal.find('.modal-body');
    const template = $('#viewTicketModalBodyTemplate').html();

    modal.data('ticket-id', ticketId);

    // Show loading state
    modalBody.html(`
        <div class="text-center p-4">
            <i class="fas fa-spinner fa-spin fa-2x"></i>
            <p class="mt-2">Loading ticket details...</p>
        </div>
    `);

    // Fetch ticket details
    $.get(`/get-ticket-details/${ticketId}`, function (data) {
        modalBody.html(template);
        populateViewTicketModal(data);
    }).fail(function() {
        modalBody.html(`
            <div class="alert alert-danger">
                Failed to load ticket details. Please try again.
            </div>
        `);
    });
});

let zoom = 1;
let zoomStep = 0.05;
let zoomCount = 0;
const zoomText = document.getElementsByClassName("zoomtext");
const zoomInBtn = document.getElementById("zoomIn");
const zoomOutBtn = document.getElementById("zoomOut");
const zoomResetBtn = document.getElementById("zoomReset");

if (zoomInBtn) {
    zoomInBtn.addEventListener("click", function () {
        if (zoomCount <= 3) {
            zoom += zoomStep;
            for (let i = 0; i < zoomText.length; i++) {
                zoomText[i].style.transform = "scale(" + zoom + ")";
            }
            zoomCount += 1;
        }
    });
}

if (zoomOutBtn) {
    zoomOutBtn.addEventListener("click", function () {
        if (zoomCount > 0 && zoom > zoomStep) {
            zoom -= zoomStep;
            for (let i = 0; i < zoomText.length; i++) {
                zoomText[i].style.transform = "scale(" + zoom + ")";
            }
            zoomCount -= 1;
        }
    });
}

if (zoomResetBtn) {
    zoomResetBtn.addEventListener("click", function () {
        zoom = 1;
        for (let i = 0; i < zoomText.length; i++) {
            zoomText[i].style.transform = "scale(" + zoom + ")";
        }
        zoomCount = 0;
    });
}

// Open Assign Modal
function openAssignModal(ticketId) {
    // Reset button state first
    $("#saveAssignBtn").prop('disabled', false).text('Loading...');
    
    $.get(`/get-ticket-details/${ticketId}`, function (data) {
        $("#modal-ticket-title").val(data.title);
        $("#modal-ticket-project").val(data.project);
        $("#modal-ticket-created-by").val(data.created_by);
        $("#modal-ticket-location").val(data.location);
        $("#modal-ticket-cubical").val(data.cubical);
        $("#modal-ticket-type").val(data.ticket_type);
        $("#modal-ticket-desc").val(data.desc);
        $("#modal-ticket-category").val(data.category);
        $("#assignComment").val(""); // start with empty new-comment box
        $("#assign-priority").val(data.priority || "Medium"); // Set priority in modal
        $("#assign-status").val(data.status || "Pending");
        $("#assign-user").val(data.assigned_user_id || "");
        $("#assignTicketId").val(ticketId);

        // Show/hide and populate printer movement fields
        if (data.movement_from || data.movement_to) {
            $("#modal-movement-from").val(data.movement_from);
            $("#modal-movement-to").val(data.movement_to);
            $("#modal-movement-fields").show();
        } else {
            $("#modal-movement-fields").hide();
        }

        // Load comment history and assignable users
        loadCommentHistory(ticketId, '#modal-comment-history');
        loadAssignableUsers(data.category, data.assigned_user_id);

        // Change button label based on assignment
        if (data.assigned_user_id) {
            $("#saveAssignBtn").text("Update").removeClass("btn-success").addClass("btn-primary");
        } else {
            $("#saveAssignBtn").text("Assign").removeClass("btn-primary").addClass("btn-success");
        }
    }).fail(function() {
        $("#saveAssignBtn").text("Error").prop('disabled', true);
        showToast('error', '❌ Error loading ticket details');
    });
}

// Load assignable users for the Assign modal
function loadAssignableUsers(category, currentAssignedUserId) {
    try {
        const $dropdown = $('#assign-user');
        if ($dropdown.length === 0) return;
        $dropdown.empty().append('<option value="">Loading...</option>');
        $.ajax({
            url: '/get-assignable-users',
            method: 'POST',
            data: { category: category || '' },
            success: function (data) {
                $dropdown.empty().append('<option value="">Select Admin...</option>');
                if (data && data.success && Array.isArray(data.users)) {
                    const sorted = data.users.sort((a, b) => {
                        if (a.admin_code === '1236') return -1;
                        if (b.admin_code === '1236') return 1;
                        if (category && String(category).toLowerCase() === 'software') {
                            if (a.admin_code === '1234' && b.admin_code !== '1234') return -1;
                            if (b.admin_code === '1234' && a.admin_code !== '1234') return 1;
                        }
                        if (category && String(category).toLowerCase() === 'hardware') {
                            if (a.admin_code === '1235' && b.admin_code !== '1235') return -1;
                            if (b.admin_code === '1235' && a.admin_code !== '1235') return 1;
                        }
                        return (a.first_name || '').localeCompare(b.first_name || '');
                    });
                    sorted.forEach(function (u) {
                        const selected = (currentAssignedUserId && String(u.id) === String(currentAssignedUserId)) ? 'selected' : '';
                        const label = `${u.first_name || ''} ${u.last_name || ''}`.trim();
                        $dropdown.append(`<option value="${u.id}" ${selected}>${label}</option>`);
                    });
                } else {
                    $dropdown.append('<option value="" disabled>No admins available</option>');
                }
            },
            error: function (xhr) {
                console.log('[DEBUG] Error loading assignable users:', xhr.status, xhr.responseText);
                $dropdown.empty();
                $dropdown.append('<option value="">Select Admin...</option>');
                $dropdown.append('<option value="" disabled>Error loading admins</option>');
            }
        });
    } catch (e) {
        console.error('Failed to load assignable users', e);
    }
}

function loadCommentHistory(ticketId, historyContainerSelector = '#modal-comment-history') {
    const $history = $(historyContainerSelector);
    if ($history.length === 0) return;
    $history.html('<div class="text-center text-muted p-3"><small><i class="fas fa-spinner fa-spin"></i> Loading comments...</small></div>');
    $.ajax({
        url: `/get-ticket-comments/${ticketId}`,
        method: 'GET',
        success: function (data) {
            if (data && data.success && Array.isArray(data.comments)) {
                displayCommentHistory(data.comments, historyContainerSelector);
            } else {
                displayCommentHistory([], historyContainerSelector);
            }
        },
        error: function (xhr) {
            let errorMessage = 'Unable to load comment history';
            if (xhr.status === 403) errorMessage = 'Permission denied';
            else if (xhr.status === 404) errorMessage = 'Comments not found';
            else if (xhr.status === 500) errorMessage = 'Server error';
            $history.html(`<div class="alert alert-warning small"><i class="fas fa-exclamation-triangle"></i> ${errorMessage}</div>`);
        }
    });
}

function displayCommentHistory(comments, historyContainerSelector = '#modal-comment-history') {
    const $history = $(historyContainerSelector);
    if (!comments || comments.length === 0) {
        $history.html('<div class="text-center text-muted p-3"><small><i class="fas fa-comment-slash"></i> No comments yet</small></div>');
        return;
    }
    let html = '';
    comments.forEach((c) => {
        let bg = '#e3f2fd', bd = '#2196f3', tc = '#1565c0', ic = 'fa-user-shield';
        if (c.type === 'user') { bg = '#f1f8e9'; bd = '#4caf50'; tc = '#2e7d32'; ic = 'fa-user'; }
        else if (c.type === 'system') { bg = '#f5f5f5'; bd = '#9e9e9e'; tc = '#616161'; ic = 'fa-info-circle'; }
        let name = c.user_name || (c.type === 'user' ? 'User' : (c.type === 'system' ? 'System' : 'Admin'));
        const escaped = String(c.text || 'No text').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html += `
            <div class="mb-2" style="padding: 6px 8px; background-color: ${bg}; border-left: 3px solid ${bd}; border-radius: 4px; font-size: 12px;">
                <div class="d-flex justify-content-between align-items-center mb-1">
                    <span style="font-weight: bold; color: ${tc};"><i class="fas ${ic}"></i> ${name}</span>
                    <small style="color: #666;">${c.timestamp ? `<span class="js-local-time" data-utc="${String(c.timestamp).includes('T') ? c.timestamp : (String(c.timestamp).replace(' ', 'T') + ':00Z')}">${c.timestamp}</span>` : 'N/A'}</small>
                </div>
                <div style="white-space: pre-wrap; word-wrap: break-word; line-height: 1.3;">${escaped}</div>
            </div>`;
    });
    $history.html(html);
}

// Global toast helper for all pages - shows alerts below navbar
function showToast(type, message, timeoutMs = 4000) {
    const container = document.getElementById('alert-container');
    if (!container) {
        console.warn('Alert container not found - using fallback');
        return;
    }

    const bsType = (type === 'error') ? 'danger' : (type || 'info');
    const $toast = $(`
        <div class="alert alert-${bsType} alert-dismissible fade show shadow-sm" role="alert">
            <div class="alert-content">${message}</div>
            <button type="button" class="close" data-dismiss="alert" aria-label="Close">
                <span aria-hidden="true">&times;</span>
            </button>
        </div>
    `);

    $(container).append($toast);

    // Auto dismiss
    setTimeout(function () {
        $toast.fadeOut(400, function () { $(this).remove(); });
    }, timeoutMs);
}

// Backward compatibility
function showSuccessMessage(message, timeoutMs = 4000) {
    showToast('success', message, timeoutMs);
}

$(document).ready(function () {
    // Modal confirmation handler for user ticket actions
    const $confirmModal = $('#confirmActionModal');
    let confirmAction = null; // function to call on confirm

    function openConfirm({ title, text, detailsHtml, confirmBtnClass = 'btn-danger', confirmIcon = 'fa-trash', confirmText = 'Confirm', onConfirm }) {
        $('#confirmActionLabel').text(title || 'Confirm Action');
        $('#confirmActionText').text(text || 'Are you sure?');
        const $details = $('#confirmActionDetails');
        if (detailsHtml) { $details.html(detailsHtml).show(); }
        else { $details.hide().empty(); }

        const $btn = $('#confirmActionBtn');
        $btn.removeClass('btn-danger btn-primary btn-warning btn-success').addClass(confirmBtnClass);
        $btn.html(`<i class="fas ${confirmIcon}"></i> ${confirmText}`);

        confirmAction = () => {
            if (typeof onConfirm === 'function') onConfirm();
        };
        $confirmModal.modal('show');
    }

    // Confirm button triggers the stored action, then closes
    $('#confirmActionBtn').off('click').on('click', function () {
        if (typeof confirmAction === 'function') {
            const fn = confirmAction;
            confirmAction = null;
            fn();
        }
        $confirmModal.modal('hide');
    });

    // Cancel and X should close the modal and redirect to tickets page
    $confirmModal.find('[data-role="close"], .close').off('click').on('click', function () {
        $confirmModal.modal('hide');
        // Redirect to tickets page after closing modal
        setTimeout(function() {
            window.location.href = '/tickets';
        }, 200);
    });

    // Ensure modal state resets on hide
    $confirmModal.on('hidden.bs.modal', function () {
        confirmAction = null;
        $('#confirmActionText').text('Are you sure?');
        $('#confirmActionDetails').hide().empty();
        const $btn = $('#confirmActionBtn');
        $btn.removeClass('btn-primary btn-warning btn-success').addClass('btn-danger');
        $btn.html('<i class="fas fa-trash"></i> Confirm');
    });

    $(document).on('submit', '.user-comment-save-form', function (e) {
    });

    $(document).on('submit', '.user-ticket-delete-form', function (e) {
        e.preventDefault();
        const form = this;
        const ticketId = $(form).data('ticket-id');
        const title = $(form).data('ticket-title') || `#${ticketId}`;
        openConfirm({
            title: 'Confirm Ticket Deletion',
            text: `Are you sure you want to delete ticket "${title}"?`,
            detailsHtml: '<li>This action is permanent</li><li>Comments will be removed</li>',
            confirmBtnClass: 'btn-danger',
            confirmIcon: 'fa-trash',
            confirmText: 'Delete Ticket',
            onConfirm: () => form.submit()
        });
    });

    // Handle reopen ticket button clicks (use off/on to prevent duplicate handlers)
    $(document).off('click', '.reopen-ticket-btn').on('click', '.reopen-ticket-btn', function (e) {
        e.preventDefault();
        e.stopPropagation(); // Prevent event bubbling
        
        const ticketId = $(this).data('ticket-id');
        const title = $(this).data('ticket-title') || `#${ticketId}`;
        
        // Show modal with reason input
        const reasonHtml = `
            <div class="form-group">
                <label for="reopenReason">Please explain why you need to reopen this ticket:</label>
                <textarea id="reopenReason" class="form-control" rows="3" 
                         placeholder="Example: The issue still persists after the suggested solution..." 
                         required maxlength="500"></textarea>
                <small class="form-text text-muted">This helps our team understand the continued issue.</small>
            </div>
        `;
        
        openConfirm({
            title: 'Reopen Ticket',
            text: `Reopen ticket "${title}"?`,
            detailsHtml: reasonHtml,
            confirmBtnClass: 'btn-warning',
            confirmIcon: 'fa-redo',
            confirmText: 'Reopen Ticket',
            onConfirm: () => {
                const reason = $('#reopenReason').val().trim();
                if (!reason) {
                    $('#reopenReason').addClass('is-invalid');
                    return false; // Prevent modal from closing
                }
                
                // Create and submit form with reason
                const form = $('<form>', {
                    method: 'POST',
                    action: '/reopen-ticket'
                });
                form.append($('<input>', { type: 'hidden', name: 'ticket_id', value: ticketId }));
                form.append($('<input>', { type: 'hidden', name: 'reason', value: reason }));
                $('body').append(form);
                form.submit();
            }
        });
        
        // Add input validation (remove previous handlers first)
        $(document).off('input', '#reopenReason').on('input', '#reopenReason', function() {
            $(this).removeClass('is-invalid');
        });
    });
    // Ensure a single authoritative handler is bound each time the modal opens
    $('#assignTicketModal').on('show.bs.modal', function () {
        $('#saveAssignBtn').off('click.assign').on('click.assign', function (e) {
            e.preventDefault();

            const $submitBtn = $(this);
            if ($submitBtn.prop('disabled')) return false;

            const originalText = $submitBtn.text();
            $submitBtn.prop('disabled', true).text(originalText === 'Update' ? 'Updating...' : 'Assigning...');

            const data = {
                ticket_id: $('#assignTicketId').val(),
                user_id: $('#assign-user').val(),
                priority: $('#assign-priority').val(),
                status: $('#assign-status').val(),
                comment: $('#assignComment').val(),
            };

            if (!data.ticket_id) {
                showToast('error', '❌ Error: No ticket selected');
                $submitBtn.prop('disabled', false).text(originalText);
                return;
            }
            if (!data.user_id) {
                showToast('error', '❌ Error: Please select a user to assign');
                $submitBtn.prop('disabled', false).text(originalText);
                return;
            }

            $.ajax({
                url: '/assign-ticket',
                method: 'POST',
                data: data,
                success: function (response) {
                    if (response.success) {
                        // Close modal and hard refresh dashboard
                        $('#assignTicketModal').modal('hide');
                        setTimeout(function () {
                            window.location.replace('/admin-dashboard?refresh=' + new Date().getTime());
                        }, 200);
                    } else {
                        showToast('error', '❌ Error: ' + (response.error || 'Unknown error'));
                        $submitBtn.prop('disabled', false).text(originalText);
                    }
                },
                error: function (xhr, textStatus) {
                    showToast('error', '❌ Error assigning ticket: ' + (xhr.responseJSON?.error || xhr.responseText || textStatus || 'Unknown error'));
                    $submitBtn.prop('disabled', false).text(originalText);
                }
            });
        });
    });

    $(document).on('click', '.assign-btn', function () {
        const ticketId = $(this).data('ticket-id');
        // Reset UI state
        $('#modal-comment-history').html('<div class="text-center text-muted"><small>Loading comment history...</small></div>');
        $('#assignComment').val('');
        openAssignModal(ticketId);
    });

    $(document).on('click', '.admin-comment-save', function () {
        const ticketId = $(this).data('ticket-id');
        const $input = $(`.admin-comment-input[data-ticket-id='${ticketId}']`);
        const comment = $input.val();

        const $btn = $(this);
        $btn.prop('disabled', true).text('Saving...');

        $.ajax({
            url: `/update-comment/${ticketId}`,
            method: 'POST',
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
            contentType: 'application/json',
            data: JSON.stringify({ comment }),
            success: function (response) {
                if (response.success) {
                    $input.addClass('is-valid');
                    setTimeout(() => {
                        // Reload page so updated comments and status are visible
                        window.location.reload();
                    }, 1500);
                    if (response.reopened) {
                        showSuccessMessage('⚠️ TICKET REOPENED: Issue not resolved - Admin notified');
                    } else {
                        showSuccessMessage('💬 Comment saved');
                    }
                } else {
                    showToast('error', '❌ Error: ' + (response.error || 'Unknown error'));
                    $btn.prop('disabled', false).text('Save');
                }
            },
            error: function (xhr) {
                showToast('error', '❌ Error saving comment: ' + (xhr.responseJSON?.error || xhr.responseText || 'Unknown error'));
                $btn.prop('disabled', false).text('Save');
            }
        });
    });

    $('#assignTicketModal').on('hidden.bs.modal', function () {
        $('#assignTicketForm')[0].reset();
        $('#saveAssignBtn').prop('disabled', false).text('Assign').removeClass("btn-primary").addClass("btn-success");
    });

    // ===========================
    // USER MANAGEMENT FUNCTIONALITY
    // ===========================
    
    // Add User Modal Handler
    $(document).on('click', '#addUserBtn', function () {
        showUserModal('add');
    });

    // Delegate clicks for Edit/Delete buttons in user table
    $(document).on('click', '[data-action="edit-user"]', function () {
        const userId = $(this).data('user-id');
        if (userId) editUser(userId);
    });
    $(document).on('click', '[data-action="delete-user"]', function () {
        const userId = $(this).data('user-id');
        if (userId) deleteUser(userId);
    });
    
    // Handle user form submission
    $(document).on('click', '#saveUserBtn', function (e) {
        e.preventDefault();
        const action = $(this).data('action');
        saveUser(action);
    });
    
    // Handle admin type selection
    $(document).on('change', '#userAccountType', function () {
        toggleAdminFields();
    });



    // USER MODAL - Clean up when hidden and redirect appropriately
    // Handle both Bootstrap 4 and 5 events
    $(document).on('hidden.bs.modal hide.bs.modal', '#userModal', function () {
        const wasSaved = $(this).data('user-saved');
        
        // Small delay to ensure modal is fully hidden before redirect
        setTimeout(() => {
            $(this).remove();
            
            // If not saved, redirect back to User Management
            if (!wasSaved) {
                window.location.href = '/user-management';
            }
        }, 100);
    });

    // DELETE MODAL - Clean up when hidden and redirect if not deleted
    // Handle both Bootstrap 4 and 5 events
    $(document).on('hidden.bs.modal hide.bs.modal', '#deleteUserModal', function () {
        const wasDeleted = $(this).data('user-deleted');
        
        // Small delay to ensure modal is fully hidden before redirect
        setTimeout(() => {
            $(this).remove();
            
            // If not deleted (cancelled), redirect back to user management
            if (!wasDeleted) {
                window.location.href = '/user-management';
            }
        }, 100);
    });

    // DIRECT CLICK HANDLERS for modal close/cancel buttons
    $(document).on('click', '#userModal .close, #userModal [data-dismiss="modal"]', function() {
        setTimeout(() => {
            window.location.href = '/user-management';
        }, 200);
    });

    $(document).on('click', '#deleteUserModal .close, #deleteUserModal [data-dismiss="modal"]', function() {
        setTimeout(() => {
            window.location.href = '/user-management';
        }, 200);
    });

    // ESC key handler for modals
    $(document).on('keydown', function(e) {
        if (e.key === 'Escape') {
            if ($('#userModal').hasClass('show')) {
                setTimeout(() => {
                    window.location.href = '/user-management';
                }, 200);
            } else if ($('#deleteUserModal').hasClass('show')) {
                setTimeout(() => {
                    window.location.href = '/user-management';
                }, 200);
            }
        }
    });

    // ===========================
    // MODERN SEARCH BAR FUNCTIONALITY
    // ===========================
    
    $(document).ready(function() {
        // Initialize search for both admin and user pages
        initializeSearch('#adminTableSearch', '#searchClearBtn', '/admin-dashboard');
        initializeSearch('#userTableSearch', '#userSearchClearBtn', '/tickets');
    });
    
    function initializeSearch(searchInputSelector, clearBtnSelector, searchUrl) {
    
        const $searchInput = $(searchInputSelector);
    
        const $clearBtn = $(clearBtnSelector);
    
        
    
        if ($searchInput.length === 0) return; // Only run on pages with search
    
        
    
        function performSearch() {
    
            const query = $searchInput.val().trim();
    
            // Redirect to the search URL with the query
    
            window.location.href = searchUrl + '?q=' + encodeURIComponent(query);
    
        }
    
        
    
        // Clear button handler - refresh to original page (remove filters and query params)
    
        $clearBtn.on('click', function() {
    
            window.location.href = searchUrl;
    
        });
    
        
    
        // ESC key to clear search
    
        $searchInput.on('keydown', function(e) {
    
            if (e.key === 'Escape') {
    
                $searchInput.val('');
    
                window.location.href = searchUrl;
    
            }
    
        });
    
        
    
        // Enter key to prevent form submission if wrapped in form
    
        $searchInput.on('keydown', function(e) {
    
            if (e.key === 'Enter') {
    
                e.preventDefault();
    
                performSearch();
    
            }
    
        });
    
    }});

// ===========================
// USER MANAGEMENT FUNCTIONS
// ===========================

function editUser(userId) {
    // Fetch user details
    $.get(`/get-user/${userId}`)
        .done(function(response) {
            if (response.success) {
                showUserModal('edit', response.user);
            } else {
                showToast('error', '❌ Error: ' + (response.error || 'Failed to load user details'));
            }
        })
        .fail(function(xhr) {
            const errorMsg = xhr.responseJSON?.error || xhr.responseText || 'Failed to load user details';
            showToast('error', '❌ Error: ' + errorMsg);
        });
}

function deleteUser(userId) {
    // First get user details for confirmation
    $.get(`/get-user/${userId}`)
        .done(function(response) {
            if (response.success) {
                const user = response.user;
                const userName = `${user.first_name} ${user.last_name || ''}`.trim();
                showDeleteConfirmModal(userId, userName);
            } else {
                showToast('error', '❌ Error: ' + (response.error || 'Failed to load user details'));
            }
        })
        .fail(function(xhr) {
            const errorMsg = xhr.responseJSON?.error || xhr.responseText || 'Failed to load user details';
            showToast('error', '❌ Error: ' + errorMsg);
        });
}

function showUserModal(action, userData = null) {
    const isEdit = action === 'edit';
    const modalTitle = isEdit ? 'Edit User' : 'Add New User';
    const buttonText = isEdit ? 'Update User' : 'Add User';
    const buttonClass = isEdit ? 'btn-primary' : 'btn-success';
    
    // Pre-fill data if editing
    const firstNameValue = userData?.first_name || '';
    const lastNameValue = userData?.last_name || '';
    const emailValue = userData?.email || '';
    const accountTypeValue = userData?.accountType || 'user';
    const adminCodeValue = userData?.admin_code || '';
    const adminRoleValue = userData?.admin_role || '';
    const userIdValue = userData?.id || '';    
    const showEmailField = !isEdit || (isEdit && userData?.accountType === 'admin');
    
    // Role fields will be shown initially and then permissions will be applied
    // This allows regular admins to see role fields for regular users
    
    const modalHtml = `
        <div class="modal fade" id="userModal" tabindex="-1" role="dialog" aria-labelledby="userModalLabel" aria-hidden="true">
            <div class="modal-dialog" role="document">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="userModalLabel">${modalTitle}</h5>
                        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
                            <span aria-hidden="true">&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        <form id="userForm">
                            ${isEdit ? `<input type="hidden" id="userId" value="${userIdValue}">` : ''}
                            
                            <div class="form-group">
                                <label for="userFirstName">First Name *</label>
                                <input type="text" class="form-control" id="userFirstName" value="${firstNameValue}" required>
                            </div>
                            
                            <div class="form-group">
                                <label for="userLastName">Last Name</label>
                                <input type="text" class="form-control" id="userLastName" value="${lastNameValue}">
                            </div>
                            
                            ${showEmailField ? `
                                <div class="form-group">
                                    <label for="userEmail">Email *</label>
                                    <input type="email" class="form-control" id="userEmail" value="${emailValue}" required>
                                </div>
                            ` : `<input type="hidden" id="userEmail" value="${emailValue}">`}

                            <div class="form-group">
                                <label for="userPassword">Password ${isEdit ? '(leave blank to keep current)' : '*'}</label>
                                <input type="password" class="form-control" id="userPassword" ${!isEdit ? 'required' : ''}>
                                <small class="form-text text-muted">
                                    ${isEdit ? 'Only enter a password if you want to change it' : 'Minimum 6 characters recommended'}
                                </small>
                            </div>
                            
                            <div class="form-group">
                                <label for="userAccountType">Account Type *</label>
                                <select class="form-control" id="userAccountType" required>
                                    <option value="user" ${accountTypeValue === 'user' ? 'selected' : ''}>User</option>
                                    <option value="admin" ${accountTypeValue === 'admin' ? 'selected' : ''}>Admin</option>
                                </select>
                            </div>
                            
                            <div id="adminFields" style="display: ${accountTypeValue === 'admin' ? 'block' : 'none'};">
                                <div class="form-group">
                                    <label for="userAdminType">Admin Type</label>
                                    <select class="form-control" id="userAdminType">
                                        <option value="">Select Admin Type</option>
                                        <option value="1236" ${adminCodeValue === '1236' ? 'selected' : ''}>Super Admin</option>
                                        <option value="1234" ${adminCodeValue === '1234' ? 'selected' : ''}>IT Admin</option>
                                        <option value="1235" ${adminCodeValue === '1235' ? 'selected' : ''}>Hardware Admin</option>
                                    </select>
                                    <small class="form-text text-muted">“Admin” maps to Super Admin access.</small>
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                        <button type="button" class="btn ${buttonClass}" id="saveUserBtn" data-action="${action}">${buttonText}</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    $('#userModal').remove();
    
    // Add modal to body and show it
    $('body').append(modalHtml);
    $('#userModal').modal('show');
    
    // Set up account type change handler
    $('#userAccountType').on('change', toggleAdminFields);
    
    // Initialize admin fields toggle
    toggleAdminFields();
    
    // Apply role-based permissions after modal is loaded
    applyRoleBasedPermissions(action, userData);
}

function applyRoleBasedPermissions(action, userData) {
    const isEdit = action === 'edit';
    const currentUserAdminCode = window.currentUserAdminCode || '';
    const currentUserEmail = window.currentUserEmail || '';
    const isSuperAdmin = currentUserAdminCode === '1236';
    const isRegularAdmin = ['1234', '1235'].includes(currentUserAdminCode);
    const targetIsAdmin = userData?.accountType === 'admin';
    const isEditingSelf = isEdit && userData && userData.email === currentUserEmail;
    const isRegularUser = !isSuperAdmin && !isRegularAdmin;
    
    console.log('Applying permissions:', {
        isEdit, currentUserAdminCode, isSuperAdmin, isRegularAdmin, targetIsAdmin, isEditingSelf
    });
    
    // IMPORTANT: NO ONE can edit their own roles - not even Super Admin
    // This prevents accidental self-demotion and ensures role changes require another admin
    if (isEditingSelf) {
        $('#userAccountType').prop('disabled', true);
        $('#userAdminType').prop('disabled', true);
        
        // Add notice for self-editing
        if (!$('#selfEditNotice').length) {
            $('#userAccountType').closest('.form-group').after(`
                <div id="selfEditNotice" class="alert alert-info">
                    <i class="fas fa-user-shield"></i>
                    <strong>Security Policy:</strong> You cannot modify your own account type or admin privileges. 
                    Another administrator must make role changes for you.
                </div>
            `);
        }
        return; // Exit early - no further permissions needed
    }
    
    // Super Admin can edit OTHERS (but not themselves, handled above)
    if (isSuperAdmin && !isEditingSelf) {
        // Super Admin can edit other users' roles - no restrictions
        return;
    }
    
    // Regular Admins can edit regular users (including roles) but not other admins
    if (isRegularAdmin) {
        if (targetIsAdmin && isEdit) {
            // Cannot edit other admin users at all
            $('#saveUserBtn').prop('disabled', true).html('<i class="fas fa-ban"></i> Cannot Edit Admin User');
            $('#userAccountType').prop('disabled', true);
            $('#userAdminType').prop('disabled', true);
            
            // Add major warning
            if (!$('#adminEditWarning').length) {
                $('#userForm').prepend(`
                    <div id="adminEditWarning" class="alert alert-danger">
                        <i class="fas fa-exclamation-triangle"></i>
                        <strong>Access Denied:</strong> You cannot edit other admin users. 
                        Contact a Super Administrator for changes to admin accounts.
                    </div>
                `);
            }
        } else {
            // Regular admin editing regular user or adding new user - allow role changes
            // No restrictions needed - they can modify roles for regular users
            return;
        }
    }
    
    // Regular users cannot see or modify role fields at all
    if (isRegularUser) {
        $('#userAccountType').prop('disabled', true);
        $('#userAdminType').prop('disabled', true);
        
        if (!$('#rolePermissionNotice').length) {
            $('#userAccountType').closest('.form-group').after(`
                <div id="rolePermissionNotice" class="alert alert-warning">
                    <i class="fas fa-info-circle"></i>
                    <strong>Note:</strong> Only administrators can assign roles.
                </div>
            `);
        }
    }
}

function toggleAdminFields() {
    const accountType = $('#userAccountType').val();
    const adminFields = $('#adminFields');
    
    if (accountType === 'admin') {
        adminFields.slideDown();
    } else {
        adminFields.slideUp();
        // Clear admin fields when hiding
        $('#userAdminType').val('');
    }
}

function openUserModal(action) {
    if (action === 'add') {
        showUserModal('add');
    } else {
        console.error('Unknown action:', action);
    }
}

function saveUser(action) {
    const isEdit = action === 'edit';
    const $btn = $('#saveUserBtn');
    const originalText = $btn.text();
    
    // Prevent multiple submissions
    if ($btn.prop('disabled')) {
        return;
    }
    
    $btn.prop('disabled', true).text(isEdit ? 'Updating...' : 'Adding...');
    
    // Collect form data
    const formData = new FormData();
    formData.append('first_name', $('#userFirstName').val().trim());
    formData.append('last_name', $('#userLastName').val().trim());
    formData.append('email', $('#userEmail').val().trim());
    formData.append('password', $('#userPassword').val());
    formData.append('account_type', $('#userAccountType').val());
    // Map single Admin Type selection to backend fields
    const selectedAdminCode = $('#userAdminType').val() || '';
    let mappedRole = '';
    if (selectedAdminCode === '1236') mappedRole = 'Super Admin';
    else if (selectedAdminCode === '1234') mappedRole = 'IT Admin';
    else if (selectedAdminCode === '1235') mappedRole = 'Hardware Admin';
    formData.append('admin_code', selectedAdminCode);
    formData.append('admin_role', mappedRole);
    
    if (isEdit) {
        formData.append('user_id', $('#userId').val());
    }
    
    // Validation
    if (!formData.get('first_name') || (!isEdit && !formData.get('email'))) {
        showToast('error', '❌ Please fill in all required fields');
        $btn.prop('disabled', false).text(originalText);
        return;
    }
    
    if (!isEdit && !formData.get('password')) {
        showToast('error', '❌ Password is required for new users');
        $btn.prop('disabled', false).text(originalText);
        return;
    }
    
    // Submit form
    const url = isEdit ? '/edit-user' : '/add-user';
    
    $.ajax({
        url: url,
        method: 'POST',
        data: formData,
        processData: false,
        contentType: false,
        success: function(response) {
            if (response.success) {
                $('#userModal').data('user-saved', true).modal('hide');
                showSuccessMessage('✅ ' + response.message);
                // Reload page to show updated user list
                setTimeout(() => {
                    window.location.href = '/user-management';
                }, 1500);
            } else {
                showToast('error', '❌ Error: ' + (response.error || 'Unknown error'));
                $btn.prop('disabled', false).text(originalText);
            }
        },
        error: function(xhr) {
            const errorMsg = xhr.responseJSON?.error || xhr.responseText || 'Unknown error';
            showToast('error', '❌ Error: ' + errorMsg);
            $btn.prop('disabled', false).text(originalText);
        }
    });
}

function showDeleteConfirmModal(userId, userName) {
    const modalHtml = `
        <div class="modal fade" id="deleteUserModal" tabindex="-1" role="dialog" aria-labelledby="deleteUserModalLabel" aria-hidden="true">
            <div class="modal-dialog" role="document">
                <div class="modal-content">
                    <div class="modal-header bg-danger text-white">
                        <h5 class="modal-title" id="deleteUserModalLabel">⚠️ Confirm User Deletion</h5>
                        <button type="button" class="close text-white" data-dismiss="modal" aria-label="Close">
                            <span aria-hidden="true">&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        <div class="alert alert-warning">
                            <i class="fas fa-exclamation-triangle"></i>
                            <strong>Warning:</strong> This action cannot be undone!
                        </div>
                        <p>Are you sure you want to delete user <strong>"${userName}"</strong>?</p>
                        <p class="text-muted small">
                            • All tickets created by this user will be marked as "${userName} (Deleted User)"<br>
                            • Any ticket assignments will be unassigned<br>
                            • All notifications will be removed<br>
                            • This action is permanent
                        </p>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-danger" id="confirmDeleteBtn" data-user-id="${userId}">
                            <i class="fas fa-trash"></i> Delete User
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    $('#deleteUserModal').remove();
    
    // Add modal to body and show it
    $('body').append(modalHtml);
    $('#deleteUserModal').modal('show');
    
    // Handle delete confirmation
    $('#confirmDeleteBtn').on('click', function() {
        const $btn = $(this);
        const userId = $btn.data('user-id');
        
        $btn.prop('disabled', true).text('Deleting...');
        
        // Submit delete request
        $.ajax({
            url: '/delete-user',
            method: 'POST',
            data: { user_id: userId },
            success: function(response) {
                if (response.success) {
                    $('#deleteUserModal').data('user-deleted', true).modal('hide');
                    showSuccessMessage('✅ ' + response.message);
                    // Reload page to show updated user list
                    setTimeout(() => {
                        window.location.href = '/user-management';
                    }, 1500);
                } else {
                    showToast('error', '❌ Error: ' + (response.error || 'Unknown error'));
                }
            },
            error: function(xhr) {
                const errorMsg = xhr.responseJSON?.error || xhr.responseText || 'Unknown error';
                showToast('error', '❌ Error deleting user: ' + errorMsg);
            },
            complete: function() {
                $btn.prop('disabled', false).text('Delete User');
            }
        });
    });
    

}

// ===========================
// MODERN SEARCH BAR FUNCTIONALITY
// ===========================

$(document).ready(function() {
    // Initialize search for both admin and user pages
    initializeSearch('#adminTableSearch', '#searchClearBtn', '#searchResultsInfo', '#searchResultsText');
    initializeSearch('#userTableSearch', '#userSearchClearBtn', '#userSearchResultsInfo', '#userSearchResultsText');
});

function initializeSearch(searchInputSelector, clearBtnSelector, resultsInfoSelector, resultsTextSelector) {
    const $searchInput = $(searchInputSelector);
    const $clearBtn = $(clearBtnSelector);
    const $resultsInfo = $(resultsInfoSelector);
    const $resultsText = $(resultsTextSelector);
    
    if ($searchInput.length === 0) return; // Only run on pages with search
    
    let searchTimeout;
    
    // Search functionality
    function performSearch() {
        const query = $searchInput.val().toLowerCase().trim();
        const $tableRows = $('.table tbody tr');
        let visibleCount = 0;
        let totalRows = $tableRows.length;
        
        // Handle empty table message row
        const $emptyRow = $tableRows.filter(':has(.table-empty)');
        if ($emptyRow.length > 0) {
            totalRows = totalRows - 1;
        }
        
        if (query === '') {
            // Show all rows
            $tableRows.removeClass('search-hidden');
            $tableRows.find('.search-highlight').removeClass('search-highlight');
            $resultsInfo.hide();
            $clearBtn.hide();
            return;
        }
        
        $clearBtn.show();
        
        // Search through each row
        $tableRows.each(function() {
            const $row = $(this);
            
            // Skip empty table message row
            if ($row.find('.table-empty').length > 0) {
                return;
            }
            
            // Clear previous highlights
            $row.find('.search-highlight').each(function() {
                const $this = $(this);
                $this.replaceWith($this.text());
            });
            
            // Enhanced search - collect all searchable data
            let searchableContent = [];
            
            // Get all cell text content
            $row.find('td').each(function(index) {
                const $cell = $(this);
                const cellText = $cell.text().trim();
                
                // Skip empty cells and action buttons
                if (cellText && !$cell.find('button').length && !$cell.find('form').length) {
                    searchableContent.push(cellText.toLowerCase());
                }
                
                // Special handling for specific columns that might contain IDs
                if (index === 0) {
                    // First column is Ticket ID - ensure it's searchable
                    searchableContent.push('ticket' + cellText.toLowerCase());
                    searchableContent.push('id' + cellText.toLowerCase());
                    searchableContent.push('#' + cellText.toLowerCase());
                }
                
                // Extract data attributes that might contain IDs
                const ticketId = $cell.find('[data-ticket-id]').attr('data-ticket-id');
                if (ticketId) {
                    searchableContent.push(ticketId.toLowerCase());
                    searchableContent.push('ticket' + ticketId.toLowerCase());
                    searchableContent.push('#' + ticketId.toLowerCase());
                }
            });
            
            // Also check for user IDs in data attributes
            const userElements = $row.find('[data-user-id], [data-assigned-user]');
            userElements.each(function() {
                const userId = $(this).attr('data-user-id') || $(this).attr('data-assigned-user');
                if (userId) {
                    searchableContent.push(userId.toLowerCase());
                    searchableContent.push('user' + userId.toLowerCase());
                }
            });
            
            // Combine all searchable content
            const allSearchableText = searchableContent.join(' ');
            
            // Check if query matches any searchable content
            const isMatch = searchableContent.some(content => {
                return content.includes(query) ||
                       // Support partial ID searches
                       (query.length >= 2 && content.includes(query)) ||
                       // Support searches with # prefix for IDs
                       (query.startsWith('#') && content.includes(query.substring(1))) ||
                       // Support searches with 'ticket' prefix
                       (query.startsWith('ticket') && content.includes(query.substring(6))) ||
                       // Support searches with 'user' prefix
                       (query.startsWith('user') && content.includes(query.substring(4)));
            });
            
            if (isMatch) {
                $row.removeClass('search-hidden');
                visibleCount++;
                
                // Highlight matching text in visible cells
                $row.find('td').each(function() {
                    const $cell = $(this);
                    const cellText = $cell.text().toLowerCase();
                    
                    // Only highlight in cells without buttons or forms
                    if (cellText.includes(query) && !$cell.find('button, form, textarea').length) {
                        // Avoid highlighting in complex content containers to prevent HTML corruption
                        if ($cell.is('.remarks-column') || $cell.find('.user-remarks, #modal-comment-history').length) {
                            return;
                        }
                        const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
                        // Highlight only text nodes to avoid touching tags/attributes
                        $cell.contents().each(function() {
                            if (this.nodeType === Node.TEXT_NODE) {
                                const text = this.nodeValue;
                                if (regex.test(text)) {
                                    const safeHtml = text.replace(regex, '<span class="search-highlight">$1</span>');
                                    $(this).replaceWith(safeHtml);
                                }
                            }
                        });
                    }
                });
            } else {
                $row.addClass('search-hidden');
            }
        });
        
        // Update results info
        $resultsInfo.show();
        
        // Determine if this is users table or tickets table
        const isUserTable = searchInputSelector.includes('user');
        const itemType = isUserTable ? 'users' : 'tickets';
        
        $resultsText.text(`${visibleCount} of ${totalRows} ${itemType} found`);
        $resultsInfo.removeClass('has-results no-results');
        
        if (visibleCount > 0) {
            $resultsInfo.addClass('has-results');
        } else {
            $resultsInfo.addClass('no-results');
            $resultsText.text(`No ${itemType} match your search`);
        }
    }
    
    // Escape special regex characters
    function escapeRegExp(string) {
        return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }
    
    // Search input handler with debouncing
    $searchInput.on('input', function() {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(performSearch, 300);
    });
    
    // Clear button handler - refresh to original page (remove filters and query params)
    $clearBtn.on('click', function() {
        if (window && window.location) {
            // Reload without query parameters to restore original page state
            window.location.replace(window.location.pathname);
            return;
        }
        // Fallback (should not be needed in browsers)
        $searchInput.val('').focus();
        performSearch();
    });
    
    // ESC key to clear search
    $searchInput.on('keydown', function(e) {
        if (e.key === 'Escape') {
            $searchInput.val('');
            performSearch();
        }
    });
    
    // Enter key to prevent form submission if wrapped in form
    $searchInput.on('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
        }
    });
}
