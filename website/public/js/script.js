document.addEventListener('DOMContentLoaded', () => {
    // Theme Toggle
    const themeToggle = document.getElementById('themeToggle');
    const htmlEl = document.documentElement;
    
    // Load preference
    const savedTheme = localStorage.getItem('dsf_theme');
    if (savedTheme) {
        htmlEl.setAttribute('data-theme', savedTheme);
        themeToggle.textContent = savedTheme === 'dark' ? '☀️' : '🌙';
    }

    themeToggle.addEventListener('click', () => {
        const currentTheme = htmlEl.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
        htmlEl.setAttribute('data-theme', newTheme);
        themeToggle.textContent = newTheme === 'dark' ? '☀️' : '🌙';
        localStorage.setItem('dsf_theme', newTheme);
    });

    // Mobile Menu Toggle
    const menuToggle = document.getElementById('menuToggle');
    const categoryNav = document.getElementById('categoryNav');

    menuToggle.addEventListener('click', () => {
        const open = categoryNav.classList.toggle('active');
        menuToggle.setAttribute('aria-expanded', String(open));
    });

    // Search Functionality
    const searchToggle = document.getElementById('searchToggle');
    const searchOverlay = document.getElementById('searchOverlay');
    const closeSearch = document.getElementById('closeSearch');
    const searchInput = document.getElementById('searchInput');
    const searchResults = document.getElementById('searchResults');
    
    let searchData = [];

    // Open Search
    searchToggle.addEventListener('click', () => {
        searchOverlay.classList.add('active');
        searchInput.focus();
        if (searchData.length === 0) {
            loadSearchData();
        }
    });

    // Close Search
    closeSearch.addEventListener('click', () => {
        searchOverlay.classList.remove('active');
    });

    // Fetch Search JSON
    async function loadSearchData() {
        try {
            const path = window.BASE_PATH || './';
            const response = await fetch(`${path}search.json`);
            searchData = await response.json();
        } catch (e) {
            console.error("Error loading search.json", e);
        }
    }

    // Handle typing
    searchInput.addEventListener('input', (e) => {
        const query = e.target.value.toLowerCase().trim();
        searchResults.innerHTML = '';
        
        if (query.length < 2) return;

        const results = searchData.filter(item => 
            item.title.toLowerCase().includes(query) || 
            item.category.toLowerCase().includes(query)
        ).slice(0, 8); // Max 8 results

        if (results.length === 0) {
            searchResults.innerHTML = '<p class="no-results">No se encontraron resultados.</p>';
            return;
        }

        const path = window.BASE_PATH || './';
        results.forEach(item => {
            const el = document.createElement('a');
            el.href = `${path}${item.slug}.html`;
            el.className = 'search-result-item';
            const img = document.createElement('img');
            img.src = item.image;
            img.alt = '';
            img.loading = 'lazy';
            const details = document.createElement('div');
            const title = document.createElement('h4');
            title.textContent = item.title;
            const meta = document.createElement('span');
            meta.textContent = `${item.category} • ${item.date}`;
            details.append(title, meta);
            el.append(img, details);
            searchResults.appendChild(el);
        });
    });

    // Close search on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            searchOverlay.classList.remove('active');
        }
    });
});
