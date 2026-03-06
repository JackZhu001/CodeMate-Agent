(() => {
  const menuBtn = document.getElementById('menu-btn');
  const navLinks = document.getElementById('nav-links');
  if (menuBtn && navLinks) {
    menuBtn.addEventListener('click', () => navLinks.classList.toggle('open'));
    navLinks.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => navLinks.classList.remove('open'));
    });
  }

  const revealEls = document.querySelectorAll('.reveal');
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) entry.target.classList.add('show');
    });
  }, { threshold: 0.15 });
  revealEls.forEach(el => io.observe(el));

  const sections = ['overview', 'capabilities', 'scenarios', 'architecture', 'notes', 'comparison', 'onboarding'];
  const links = [...document.querySelectorAll('.nav-links a')];
  const syncActive = () => {
    const y = window.scrollY + 120;
    let current = sections[0];
    for (const id of sections) {
      const sec = document.getElementById(id);
      if (sec && sec.offsetTop <= y) current = id;
    }
    links.forEach(link => {
      const active = link.getAttribute('href') === `#${current}`;
      link.classList.toggle('active', active);
    });
  };
  document.addEventListener('scroll', syncActive, { passive: true });
  syncActive();

  const progressEl = document.getElementById('scroll-progress');
  const updateProgress = () => {
    if (!progressEl) return;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = max > 0 ? (window.scrollY / max) * 100 : 0;
    progressEl.style.width = `${Math.min(100, Math.max(0, ratio))}%`;
  };
  document.addEventListener('scroll', updateProgress, { passive: true });
  updateProgress();
})();
