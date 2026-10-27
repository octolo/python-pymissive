(function () {
    "use strict";

    const root = document.getElementById("scheduler-root");
    if (!root) {
        return;
    }

    const jsonUrl = root.dataset.jsonUrl;
    const pollMs = Number(root.dataset.pollMs || 2000);
    const labels = {
        updated: root.dataset.labelUpdated || "Updated",
        errors: root.dataset.labelErrors || "error(s)",
        err: root.dataset.labelErr || "err",
        cancelled: root.dataset.labelCancelled || "Cancelled",
        empty: root.dataset.labelEmpty || "No missives attached to this run yet.",
        stopped: root.dataset.labelStopped || "Live updates stopped. Reload the page.",
    };
    // A scheduled run may start hours later: check it, but less often.
    const pendingPollMs = pollMs * 5;
    const maxRetryMs = 60000;
    let retryMs = pollMs * 2;
    const emptyItem = '<li class="type-empty">' + escapeHtml(labels.empty) + "</li>";

    const els = {
        status: root.querySelector(".scheduler-status"),
        updated: document.getElementById("scheduler-updated"),
        overallStats: document.getElementById("scheduler-overall-stats"),
        overallBar: document.getElementById("scheduler-overall-bar"),
        overallErrors: document.getElementById("scheduler-overall-errors"),
        averageSpeed: document.getElementById("scheduler-average-speed"),
        averageSpeedValue: document.getElementById("scheduler-average-speed-value"),
        cancel: document.getElementById("scheduler-cancel"),
        typeList: document.getElementById("scheduler-type-list"),
        statusList: document.getElementById("scheduler-status-list"),
        jsonPre: document.getElementById("scheduler-json-pre"),
    };

    function formatUpdated() {
        if (!els.updated) {
            return;
        }
        const now = new Date();
        els.updated.textContent = labels.updated + ": " + now.toLocaleTimeString();
    }

    function renderTypeList(byType) {
        if (!els.typeList) {
            return;
        }
        const entries = Object.entries(byType || {});
        if (!entries.length) {
            els.typeList.innerHTML = emptyItem;
            return;
        }

        els.typeList.innerHTML = entries
            .map(function ([typeKey, data]) {
                const errorPct = data.total > 0
                    ? Math.round((data.error / data.total) * 100)
                    : 0;
                const errorBadge = data.error > 0
                    ? '<span class="type-errors-badge">' + data.error + " " + escapeHtml(labels.err) + "</span>"
                    : "";
                const errorBar = data.error > 0
                    ? '<div class="progress-bar progress-bar--error" style="width:' + errorPct + '%"></div>'
                    : "";
                return (
                    '<li class="type-item" data-type="' + typeKey + '">' +
                    '<div class="type-item-head">' +
                    '<span class="type-label">' + escapeHtml(data.label) + "</span>" +
                    '<span class="type-stats">' +
                    data.sent + " / " + data.total + " (" + data.progress + "%)" +
                    "</span>" +
                    errorBadge +
                    "</div>" +
                    '<div class="progress-track" aria-hidden="true">' +
                    '<div class="progress-bar" style="width:' + data.progress + '%"></div>' +
                    errorBar +
                    "</div>" +
                    "</li>"
                );
            })
            .join("");
    }

    function renderStatusList(byStatus) {
        if (!els.statusList) {
            return;
        }
        const entries = Object.entries(byStatus || {});
        if (!entries.length) {
            els.statusList.innerHTML = emptyItem;
            return;
        }

        els.statusList.innerHTML = entries
            .map(function ([statusKey, data]) {
                return (
                    '<li class="status-chip" data-status="' + escapeHtml(statusKey) + '">' +
                    '<span class="status-chip-count">' + data.count + "</span>" +
                    '<span class="status-chip-label">' + escapeHtml(data.label) + "</span>" +
                    "</li>"
                );
            })
            .join("");
    }

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function applyPayload(data) {
        if (els.status) {
            els.status.textContent = data.status;
            els.status.dataset.status = data.status;
        }
        if (els.overallStats) {
            els.overallStats.textContent =
                data.total_sent_count +
                " / " +
                data.total_count +
                " (" +
                data.progress +
                "%)";
        }
        if (els.overallBar) {
            els.overallBar.style.width = data.progress + "%";
        }
        if (els.averageSpeed && els.averageSpeedValue) {
            if (data.average_send_speed == null) {
                els.averageSpeed.hidden = true;
            } else {
                els.averageSpeed.hidden = false;
                els.averageSpeedValue.textContent = data.average_send_speed_display;
            }
        }
        if (els.overallErrors) {
            if (data.total_error_count) {
                els.overallErrors.hidden = false;
                els.overallErrors.textContent =
                    data.total_error_count + " " + labels.errors;
            } else {
                els.overallErrors.hidden = true;
            }
        }
        if (els.cancel) {
            if (data.status === "cancelled") {
                els.cancel.hidden = false;
                els.cancel.textContent = data.cancel_reason
                    ? labels.cancelled + ": " + data.cancel_reason
                    : labels.cancelled;
            } else {
                els.cancel.hidden = true;
            }
        }
        renderTypeList(data.by_type);
        renderStatusList(data.by_status);
        if (els.jsonPre) {
            els.jsonPre.textContent = JSON.stringify(data, null, 2);
        }
        formatUpdated();
    }

    function fetchProgress() {
        return fetch(jsonUrl, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        }).then(function (response) {
            if (!response.ok) {
                const error = new Error("HTTP " + response.status);
                error.status = response.status;
                throw error;
            }
            // An expired session is redirected to the login page, served as 200 HTML.
            const type = response.headers.get("Content-Type") || "";
            if (!type.includes("application/json")) {
                const error = new Error("HTTP 401");
                error.status = 401;
                throw error;
            }
            return response.json();
        });
    }

    function nextDelay(data) {
        if (data.running) {
            return pollMs;
        }
        if (data.status === "pending") {
            return pendingPollMs;
        }
        return null;
    }

    function stop(error) {
        if (els.updated) {
            els.updated.textContent = labels.stopped + " (" + error.message + ")";
        }
    }

    function poll() {
        fetchProgress()
            .then(function (data) {
                retryMs = pollMs * 2;
                applyPayload(data);
                const delay = nextDelay(data);
                if (delay !== null) {
                    window.setTimeout(poll, delay);
                }
            })
            .catch(function (error) {
                // Logged out or run deleted: retrying cannot succeed.
                if (error.status >= 400 && error.status < 500) {
                    stop(error);
                    return;
                }
                window.setTimeout(poll, retryMs);
                retryMs = Math.min(retryMs * 2, maxRetryMs);
            });
    }

    poll();
})();
