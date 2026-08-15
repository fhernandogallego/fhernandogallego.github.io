document.querySelector('#year').textContent = String(new Date().getFullYear());

const spanish = document.documentElement.lang === 'es';
const scholarDataUrl = spanish ? '../data/scholar.json' : 'data/scholar.json';
const normalizeTitle = value => value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

fetch(scholarDataUrl, { cache: 'no-store' })
  .then(response => {
    if (!response.ok) throw new Error(`Scholar data unavailable: ${response.status}`);
    return response.json();
  })
  .then(data => {
    [
      'total_citations',
      'citations_5y',
      'hindex',
      'hindex5y',
      'i10index',
      'i10index5y',
      'citations_current_year'
    ].forEach(key => {
      if (data[key] === null || data[key] === undefined) return;
      document.querySelectorAll(`[data-scholar="${key}"]`).forEach(element => {
        element.textContent = new Intl.NumberFormat(document.documentElement.lang).format(data[key]);
      });
    });
    if (data.updated_at) {
      const date = data.updated_at.slice(0, 10);
      document.querySelectorAll('[data-scholar-updated]').forEach(element => {
        element.dateTime = date;
        element.textContent = date;
      });
    }
    const publications = new Map((data.publications || []).map(paper => [normalizeTitle(paper.title), paper]));
    document.querySelectorAll('.publication').forEach(publication => {
      const title = publication.querySelector('[itemprop="headline"]')?.textContent;
      const paper = title ? publications.get(normalizeTitle(title)) : null;
      if (!paper || paper.citations === null || paper.citations === undefined) return;
      let citations = publication.querySelector('[data-scholar-citations]');
      if (!citations) {
        citations = document.createElement('span');
        citations.className = 'citation-live';
        citations.dataset.scholarCitations = '';
        publication.querySelector('.pub-doi')?.append(citations);
      }
      citations.textContent = `${paper.citations} ${spanish ? 'citas' : 'citations'}`;
    });
  })
  .catch(error => console.info(error.message));
