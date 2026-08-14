if (!document.querySelector('link[href$="responsive-fixes.css"]')) {
  const fixes = document.createElement('link');
  fixes.rel = 'stylesheet';
  fixes.href = location.pathname.includes('/es/') ? '../css/responsive-fixes.css' : 'css/responsive-fixes.css';
  document.head.append(fixes);
}

const header = document.querySelector('.site-header');
const menuButton = document.querySelector('.menu-button');
const nav = document.querySelector('#site-nav');
const updateHeader = () => header.classList.toggle('scrolled', scrollY > 24);
updateHeader();
addEventListener('scroll', updateHeader, { passive: true });

menuButton?.addEventListener('click', () => {
  const open = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!open));
  nav.classList.toggle('open', !open);
  document.body.style.overflow = open ? '' : 'hidden';
});

nav?.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
  menuButton?.setAttribute('aria-expanded', 'false');
  nav.classList.remove('open');
  document.body.style.overflow = '';
}));

const observer = new IntersectionObserver(entries => entries.forEach(entry => {
  if (entry.isIntersecting) {
    entry.target.classList.add('visible');
    observer.unobserve(entry.target);
  }
}), { threshold: .08 });
document.querySelectorAll('.reveal').forEach(element => observer.observe(element));
document.querySelector('#year').textContent = String(new Date().getFullYear());

const scholarDataUrl = location.pathname.includes('/es/') ? '../data/scholar.json' : 'data/scholar.json';
const normalizeTitle = value => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

fetch(scholarDataUrl, { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`Scholar data unavailable: ${response.status}`);
    return response.json();
  })
  .then(data => {
    ['total_citations', 'hindex'].forEach(key => {
      if (data[key] !== null && data[key] !== undefined) {
        document.querySelectorAll(`[data-scholar="${key}"]`).forEach(element => {
          element.textContent = new Intl.NumberFormat(document.documentElement.lang).format(data[key]);
        });
      }
    });

    if (data.updated_at) {
      const date = data.updated_at.slice(0, 10);
      document.querySelectorAll('[data-scholar-updated]').forEach(element => {
        element.dateTime = date;
        element.textContent = date;
      });
    }

    const publications = new Map(
      (data.publications || []).map(paper => [normalizeTitle(paper.title), paper])
    );
    document.querySelectorAll('.publication').forEach(article => {
      const title = article.querySelector('[itemprop="headline"]')?.textContent;
      const paper = title ? publications.get(normalizeTitle(title)) : null;
      if (!paper || paper.citations === null || paper.citations === undefined) return;
      const badge = document.createElement('span');
      badge.className = 'citation-live';
      badge.textContent = `${paper.citations} ${document.documentElement.lang === 'es' ? 'citas' : 'citations'}`;
      article.querySelector('.pub-doi')?.append(badge);
    });
  })
  .catch(error => console.info(error.message));
