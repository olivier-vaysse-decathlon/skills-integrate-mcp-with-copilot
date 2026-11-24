document.addEventListener("DOMContentLoaded", () => {
  const activitiesList = document.getElementById("activities-list");
  const activitySelect = document.getElementById("activity");
  const signupForm = document.getElementById("signup-form");
  const teacherNotice = document.getElementById("teacher-notice");
  const messageDiv = document.getElementById("message");
  const menuToggle = document.getElementById("user-menu-toggle");
  const userMenu = document.getElementById("user-menu");
  const teacherName = document.getElementById("teacher-name");
  const openLogin = document.getElementById("open-login");
  const logoutButton = document.getElementById("logout");
  const loginDialog = document.getElementById("login-dialog");
  const loginForm = document.getElementById("login-form");
  const loginError = document.getElementById("login-error");
  let session = null;
  let messageTimer;

  function showMessage(message, type) {
    clearTimeout(messageTimer);
    messageDiv.textContent = message;
    messageDiv.className = type;
    messageTimer = setTimeout(() => messageDiv.classList.add("hidden"), 5000);
  }

  function closeMenu() {
    userMenu.classList.add("hidden");
    menuToggle.setAttribute("aria-expanded", "false");
  }

  function setSession(value) {
    session = value;
    signupForm.classList.toggle("hidden", !session);
    teacherNotice.classList.toggle("hidden", !!session);
    openLogin.classList.toggle("hidden", !!session);
    logoutButton.classList.toggle("hidden", !session);
    teacherName.classList.toggle("hidden", !session);
    teacherName.textContent = session ? `Signed in as ${session.username}` : "";
  }

  function appendLabeledLine(parent, label, value) {
    const line = document.createElement("p");
    const heading = document.createElement("strong");
    heading.textContent = `${label}: `;
    line.append(heading, document.createTextNode(value));
    parent.appendChild(line);
  }

  async function fetchActivities() {
    try {
      const response = await fetch("/activities");
      if (!response.ok) {
        throw new Error(`Activity request failed (${response.status})`);
      }
      const activities = await response.json();
      const selectedActivity = activitySelect.value;
      activitiesList.replaceChildren();
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "-- Select an activity --";
      activitySelect.replaceChildren(placeholder);

      Object.entries(activities).forEach(([name, details]) => {
        const card = document.createElement("div");
        card.className = "activity-card";
        const heading = document.createElement("h4");
        heading.textContent = name;
        const description = document.createElement("p");
        description.textContent = details.description;
        card.append(heading, description);
        appendLabeledLine(card, "Schedule", details.schedule);
        appendLabeledLine(
          card,
          "Availability",
          `${details.max_participants - details.participants.length} spots left`
        );

        const participants = document.createElement("div");
        participants.className = "participants-container";
        if (details.participants.length) {
          const section = document.createElement("div");
          section.className = "participants-section";
          const title = document.createElement("h5");
          title.textContent = "Participants:";
          const list = document.createElement("ul");
          list.className = "participants-list";
          details.participants.forEach((email) => {
            const item = document.createElement("li");
            const address = document.createElement("span");
            address.className = "participant-email";
            address.textContent = email;
            item.appendChild(address);
            if (session) {
              const remove = document.createElement("button");
              remove.type = "button";
              remove.className = "delete-btn";
              remove.textContent = "❌";
              remove.setAttribute("aria-label", `Unregister ${email} from ${name}`);
              remove.addEventListener("click", () => unregister(name, email));
              item.appendChild(remove);
            }
            list.appendChild(item);
          });
          section.append(title, list);
          participants.appendChild(section);
        } else {
          const empty = document.createElement("p");
          const emphasis = document.createElement("em");
          emphasis.textContent = "No participants yet";
          empty.appendChild(emphasis);
          participants.appendChild(empty);
        }
        card.appendChild(participants);
        activitiesList.appendChild(card);

        const option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        activitySelect.appendChild(option);
      });
      activitySelect.value = selectedActivity;
    } catch (error) {
      activitiesList.textContent = "Failed to load activities. Please try again later.";
      console.error("Error fetching activities:", error);
    }
  }

  async function updateRegistration(activity, email, action, method) {
    if (!session) {
      showMessage("Please log in as a teacher first.", "error");
      return false;
    }
    try {
      const response = await fetch(
        `/activities/${encodeURIComponent(activity)}/${action}?email=${encodeURIComponent(email)}`,
        { method, headers: { "X-CSRF-Token": session.csrf_token } }
      );
      if (response.status === 401) {
        setSession(null);
        showMessage("Your session has ended. Please log in again.", "error");
        await fetchActivities();
        return false;
      }
      const result = await response.json();
      if (!response.ok) {
        showMessage(
          typeof result.detail === "string" ? result.detail : "Registration update failed.",
          "error"
        );
        return false;
      }
      showMessage(result.message, "success");
      await fetchActivities();
      return true;
    } catch (error) {
      showMessage("Failed to update the registration. Please try again.", "error");
      console.error("Error updating registration:", error);
      return false;
    }
  }

  function unregister(activity, email) {
    return updateRegistration(activity, email, "unregister", "DELETE");
  }

  menuToggle.addEventListener("click", () => {
    const opening = userMenu.classList.contains("hidden");
    userMenu.classList.toggle("hidden", !opening);
    menuToggle.setAttribute("aria-expanded", String(opening));
  });

  openLogin.addEventListener("click", () => {
    closeMenu();
    loginDialog.showModal();
    document.getElementById("username").focus();
  });

  document.getElementById("cancel-login").addEventListener("click", () => {
    loginDialog.close();
  });

  loginDialog.addEventListener("close", () => {
    loginForm.reset();
    loginError.classList.add("hidden");
    menuToggle.focus();
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    loginError.classList.add("hidden");
    try {
      const response = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: document.getElementById("username").value,
          password: document.getElementById("password").value,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        loginError.textContent =
          typeof result.detail === "string" ? result.detail : "Login failed.";
        loginError.classList.remove("hidden");
        document.getElementById("password").value = "";
        return;
      }
      setSession(result);
      loginDialog.close();
      showMessage("Teacher login successful.", "success");
      await fetchActivities();
    } catch (error) {
      loginError.textContent = "Unable to log in. Please try again.";
      loginError.classList.remove("hidden");
      console.error("Error logging in:", error);
    }
  });

  logoutButton.addEventListener("click", async () => {
    if (!session) {
      return;
    }
    try {
      const response = await fetch("/auth/logout", {
        method: "POST",
        headers: { "X-CSRF-Token": session.csrf_token },
      });
      if (!response.ok && response.status !== 401) {
        const result = await response.json();
        showMessage(
          typeof result.detail === "string" ? result.detail : "Logout failed.",
          "error"
        );
        return;
      }
      setSession(null);
      closeMenu();
      showMessage(
        response.status === 401 ? "Your session has ended." : "Logged out.",
        "success"
      );
      await fetchActivities();
    } catch (error) {
      showMessage("Unable to log out. Please try again.", "error");
      console.error("Error logging out:", error);
    }
  });

  signupForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("email").value;
    const activity = activitySelect.value;
    if (await updateRegistration(activity, email, "signup", "POST")) {
      signupForm.reset();
    }
  });

  async function initialize() {
    try {
      const response = await fetch("/auth/session", { cache: "no-store" });
      if (response.ok) {
        setSession(await response.json());
      } else if (response.status !== 401) {
        showMessage("Unable to check teacher login status.", "error");
        console.error("Session request failed:", response.status);
      }
    } catch (error) {
      showMessage("Unable to check teacher login status.", "error");
      console.error("Error checking teacher session:", error);
    }
    await fetchActivities();
  }

  initialize();
});
