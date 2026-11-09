
async function loadSystemStatus() {
    const connection = document.getElementById("connection-status");
    const database = document.getElementById("database-status");

    try {
        const response = await fetch("/api/health");

        if (!response.ok) {
            throw new Error("Backend connection failed");
        }

        const data = await response.json();

        if (connection) {
            connection.textContent =
                "Server: " + data.message;
        }

        if (database) {
            database.textContent =
                "Database: Connected successfully";
        }

    } catch (error) {
        if (connection) {
            connection.textContent =
                "Server: Disconnected";
        }

        if (database) {
            database.textContent =
                "Database: Connection unavailable";
        }

        console.error(error);
    }
}


async function loadDashboardStats() {
    try {
        const response = await fetch("/api/dashboard/stats");

        if (!response.ok) {
            throw new Error("Could not load statistics");
        }

        const data = await response.json();

        const setText = (id, value) => {
            const element = document.getElementById(id);

            if (element) {
                element.textContent = value;
            }
        };

        setText("total-users", data.total_users);
        setText("eye-tests", data.eye_tests);
        setText("hearing-tests", data.hearing_tests);

        setText(
            "completed-tests",
            data.completed_eye_tests +
            data.completed_hearing_tests
        );

    } catch (error) {
        console.error("Dashboard error:", error);
    }
}


document.addEventListener("DOMContentLoaded", () => {
    loadSystemStatus();
    loadDashboardStats();

    // Refresh real database statistics every 5 seconds.
    setInterval(loadDashboardStats, 5000);
});
