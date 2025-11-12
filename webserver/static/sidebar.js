document.addEventListener("DOMContentLoaded", ()=>{
  const sidebar = document.getElementById("sidebar");
  const toggleBtn = document.getElementById("toggleSidebar");
  const body = document.body;
  const langIcon = document.querySelector("#langToggle i");

  // Sidebar toggle
  toggleBtn.addEventListener("click", ()=>{
    sidebar.classList.toggle("expanded");
    body.classList.toggle("sidebar-expanded");
    body.classList.toggle("sidebar-collapsed");
    localStorage.setItem("sidebarExpanded", sidebar.classList.contains("expanded"));
  });

  if(localStorage.getItem("sidebarExpanded") === "false") {
    sidebar.classList.remove("expanded");
    body.classList.remove("sidebar-expanded");
    body.classList.add("sidebar-collapsed");
  } else {
    // Mặc định expanded
    sidebar.classList.add("expanded");
    body.classList.add("sidebar-expanded");
    body.classList.remove("sidebar-collapsed");
  }
  

  // Active page
  const currentPage = window.location.pathname.replace("/", "");
  document.querySelectorAll('.sidebar .nav-link[data-page]').forEach(link => {
    link.classList.toggle('active', link.dataset.page === currentPage);
  });

  // Language switching
  document.querySelectorAll(".language-item").forEach(item=>{
    item.addEventListener("click", e=>{
      e.preventDefault();
      const lang = item.getAttribute("data-lang");
      localStorage.setItem("language", lang);
      langIcon.className = lang==="en"?"fas fa-flag-usa":"fas fa-flag";
    });
  });
  const savedLang = localStorage.getItem("language") || "vi";
  langIcon.className = savedLang==="en"?"fas fa-flag-usa":"fas fa-flag";

});

function respondShare(id, table, decision) {
  const formData = new FormData();
  formData.append("id", id);
  formData.append("table", table);
  formData.append("decision", decision);

  fetch("/respond_share", {
    method: "POST",
    body: formData
  })
  .then(res => res.json())
  .then(data => {
    if (data.status === "success") {
      // Xóa khỏi modal (thu cong)
      // const row = document.getElementById("notif-" + id);
      // if (row) row.remove();
      
      // Reload lại trang nhưng thêm query để  biết mở modal
      window.location.href = window.location.pathname + "?modal=notifications";
    }
  });
}

// Nếu URL có ?modal=notifications thì tự mở modal notification
const params = new URLSearchParams(window.location.search);
if (params.get("modal") === "notifications") {
  const modal = new bootstrap.Modal(document.getElementById("notificationsModal"));
  modal.show();
}