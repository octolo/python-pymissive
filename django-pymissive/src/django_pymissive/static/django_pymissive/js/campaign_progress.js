(function () {
    "use strict";

    const root = document.getElementById("campaign-root");
    if (!root) {
        return;
    }

    const jsonUrl = root.dataset.jsonUrl;
    const pollMs = Number(root.dataset.pollMs || 2000);

    const els = {
        status: root.querySelector(".campaign-status:not(.run-status)"),
        updated: document.getElementById("campaign-updated"),
        overallStats: document.getElementById("campaign-overall-stats"),
        overallBar: document.getElementById("campaign-overall-bar"),
        overallErrors: document.getElementById("campaign-overall-errors"),
        typeList: document.getElementById("campaign-type-list"),
        runList: document.getElementById("campaign-run-list"),
        jsonPre: document.getElementById("campaign-json-pre"),
    };

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function formatUpdated() {
        if (!els.updated) return;
        els.updated.textContent = "Updated: " + new Date().toLocaleTimeString();
    }

    function renderTypeList(byType) {
        if (!els.typeList) return;
        const entries = Object.entries(byType || {});
        if (!entries.length) {
            els.typeList.innerHTML = '<li class="type-empty">No missives in this campaign yet.</li>';
            return;
        }
        els.typeList.innerHTML = entries
            .map(function ([typeKey, data]) {
                const errorPct = data.total > 0
                    ? Math.round((data.error / data.total) * 100)
                    : 0;
                const errorBadge = data.error > 0
                    ? '<span class="type-errors-badge">' + data.error + " err</span>"
                    : "";
                const errorBar = data.error > 0
                    ? '<div class="progress-bar progress-bar--error" style="width:' + errorPct + '%"></div>'
                    : "";
                return (
                    '<li class="type-item" data-type="' + escapeHtml(typeKey) + '">' +
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

    function renderRunList(runs) {
        if (!els.runList) return;
        if (!runs || !runs.length) {
            els.runList.innerHTML = '<li class="type-empty">No send runs yet.</li>';
            return;
        }
        els.runList.innerHTML = runs
            .map(function (run) {
                let dateLabel = "Pending";
                if (run.send_date) {
                    dateLabel = "Started: " + new Date(run.send_date).toLocaleString();
                } else if (run.scheduled_send_date) {
                    dateLabel = "Scheduled: " + new Date(run.scheduled_send_date).toLocaleString();
                }
                const endedPart = run.ended_at
                    ? '<span class="run-date run-date--ended">Ended: ' +
                      new Date(run.ended_at).toLocaleString() + "</span>"
                    : "";
                const linkPart = run.url
                    ? '<a class="run-link" href="' + escapeHtml(run.url) + '">Details →</a>'
                    : "";
                return (
                    '<li class="run-item">' +
                    '<div class="run-item-head">' +
                    '<span class="run-status campaign-status" data-status="' +
                    escapeHtml(run.status) + '">' + escapeHtml(run.status) + "</span>" +
                    '<span class="run-date">' + escapeHtml(dateLabel) + "</span>" +
                    endedPart +
                    linkPart +
                    "</div>" +
                    "</li>"
                );
            })
            .join("");
    }

    function applyPayload(data) {
        if (els.status) {
            els.status.textContent = data.status;
            els.status.dataset.status = data.status;
        }
        if (els.overallStats) {
            els.overallStats.textContent =
                data.sent_count + " / " + data.total_count + " (" + data.progress + "%)";
        }
        if (els.overallBar) {
            els.overallBar.style.width = data.progress + "%";
        }
        if (els.overallErrors) {
            if (data.error_count) {
                els.overallErrors.hidden = false;
                els.overallErrors.textContent = data.error_count + " error(s)";
            } else {
                els.overallErrors.hidden = true;
            }
        }
        renderTypeList(data.by_type);
        renderRunList(data.runs);
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
            if (!response.ok) throw new Error("HTTP " + response.status);
            return response.json();
        });
    }

    function poll() {
        fetchProgress()
            .then(function (data) {
                applyPayload(data);
                if (data.running) {
                    window.setTimeout(poll, pollMs);
                }
            })
            .catch(function () {
                window.setTimeout(poll, pollMs * 2);
            });
    }

    poll();
})();
