// 모바일 햄버거 메뉴 토글
(function () {
  const toggle = document.getElementById('navToggle');
  const nav    = document.getElementById('navMenu');
  if (!toggle || !nav) return;

  toggle.addEventListener('click', function () {
    const open = nav.classList.toggle('open');
    toggle.setAttribute('aria-expanded', open);
    toggle.textContent = open ? '✕' : '☰';
  });

  // 메뉴 링크 클릭 시 닫기
  nav.querySelectorAll('.nav-link').forEach(function (link) {
    link.addEventListener('click', function () {
      nav.classList.remove('open');
      toggle.textContent = '☰';
    });
  });

  // 외부 클릭 시 닫기
  document.addEventListener('click', function (e) {
    if (!toggle.contains(e.target) && !nav.contains(e.target)) {
      nav.classList.remove('open');
      toggle.textContent = '☰';
    }
  });
})();
