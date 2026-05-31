(function () {
    "use strict";

    const root = document.getElementById("scheduler-root");
    if (!root) {
        return;
    }

    const jsonUrl = root.dataset.jsonUrl;
    const pollMs = Number(root.dataset.pollMs || 2000);

    const els = {
        status: root.querySelector(".scheduler-status"),
        updated: document.getElementById("scheduler-updated"),
        overallStats: document.getElementById("scheduler-overall-stats"),
        overallBar: document.getElementById("scheduler-overall-bar"),
        overallErrors: document.getElementById("scheduler-overall-errors"),
        typeList: document.getElementById("scheduler-type-list"),
    };

    function formatUpdated() {
        if (!els.updated) {
            return;
        }
        const now = new Date();
        els.updated.textContent = "Updated: " + now.toLocaleTimeString();
    }

    function renderTypeList(byType) {
        if (!els.typeList) {
            return;
        }
        const entries = Object.entries(byType || {});
        if (!entries.length) {
            els.typeList.innerHTML =
                '<li class="type-empty">No missives attached to this run yet.</li>';
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
        if (els.overallErrors) {
            if (data.total_error_count) {
                els.overallErrors.hidden = false;
                els.overallErrors.textContent =
                    data.total_error_count + " error(s)";
            } else {
                els.overallErrors.hidden = true;
            }
        }
        renderTypeList(data.by_type);
        formatUpdated();
    }

    function fetchProgress() {
        return fetch(jsonUrl, {
            headers: { Accept: "application/json" },
            credentials: "same-origin",
        }).then(function (response) {
            if (!response.ok) {
                throw new Error("HTTP " + response.status);
            }
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
