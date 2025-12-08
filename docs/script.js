/**
 * BUSCA FORNECEDOR - Documentation Interactive Script
 * Handles navigation, expandable sections, and animations
 */

// ========================================
// INITIALIZATION
// ========================================
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initSidebar();
    initStages();
    initSchemas();
    initScrollSpy();
    initAnimations();
});

// ========================================
// NAVIGATION
// ========================================
function initNavigation() {
    const navLinks = document.querySelectorAll('.nav-link');
    
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            // Remove active from all
            navLinks.forEach(l => l.classList.remove('active'));
            // Add active to clicked
            link.classList.add('active');
            
            // Close mobile sidebar
            const sidebar = document.getElementById('sidebar');
            if (window.innerWidth <= 1024) {
                sidebar.classList.remove('open');
            }
        });
    });
}

// ========================================
// SIDEBAR MOBILE
// ========================================
function initSidebar() {
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');
    
    if (menuToggle) {
        menuToggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }
    
    // Close sidebar when clicking outside
    document.addEventListener('click', (e) => {
        if (window.innerWidth <= 1024) {
            if (!sidebar.contains(e.target) && !menuToggle.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        }
    });
}

// ========================================
// FLOW STAGES
// ========================================
function initStages() {
    // Auto-expand first stage on load
    setTimeout(() => {
        toggleStage('discovery');
    }, 500);
}

function toggleStage(stageName) {
    const content = document.getElementById(`${stageName}Content`);
    const header = content?.previousElementSibling;
    const toggle = header?.querySelector('.stage-toggle');
    
    if (content) {
        const isExpanded = content.classList.contains('expanded');
        
        // Close all stages first
        document.querySelectorAll('.stage-content').forEach(c => {
            c.classList.remove('expanded');
        });
        document.querySelectorAll('.stage-toggle').forEach(t => {
            t.textContent = '▼';
        });
        
        // Toggle current stage
        if (!isExpanded) {
            content.classList.add('expanded');
            if (toggle) toggle.textContent = '▲';
            
            // Scroll into view smoothly
            setTimeout(() => {
                header.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }, 100);
        }
    }
}

// Make toggleStage global for onclick handlers
window.toggleStage = toggleStage;

// ========================================
// SCHEMA VIEWER
// ========================================
function initSchemas() {
    // All schemas start collapsed
    document.querySelectorAll('.schema-content').forEach(content => {
        content.classList.remove('expanded');
    });
}

function toggleSchema(schemaName) {
    const schemaId = `schema${schemaName.charAt(0).toUpperCase() + schemaName.slice(1)}`;
    const content = document.getElementById(schemaId);
    const header = content?.previousElementSibling;
    const toggle = header?.querySelector('.schema-toggle');
    
    if (content) {
        const isExpanded = content.classList.contains('expanded');
        
        if (isExpanded) {
            content.classList.remove('expanded');
            if (toggle) toggle.textContent = '▼';
        } else {
            content.classList.add('expanded');
            if (toggle) toggle.textContent = '▲';
        }
    }
}

// Make toggleSchema global for onclick handlers
window.toggleSchema = toggleSchema;

// ========================================
// SCROLL SPY
// ========================================
function initScrollSpy() {
    const sections = document.querySelectorAll('.section');
    const navLinks = document.querySelectorAll('.nav-link');
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const id = entry.target.id;
                
                navLinks.forEach(link => {
                    link.classList.remove('active');
                    if (link.getAttribute('href') === `#${id}`) {
                        link.classList.add('active');
                    }
                });
            }
        });
    }, {
        rootMargin: '-20% 0px -80% 0px'
    });
    
    sections.forEach(section => {
        observer.observe(section);
    });
}

// ========================================
// ANIMATIONS
// ========================================
function initAnimations() {
    // Animate cards on scroll
    const cards = document.querySelectorAll('.card, .metric-card, .provider-card');
    
    const cardObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry, index) => {
            if (entry.isIntersecting) {
                setTimeout(() => {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }, index * 50);
                cardObserver.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1
    });
    
    cards.forEach(card => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
        cardObserver.observe(card);
    });
    
    // Animate progress bars
    const bars = document.querySelectorAll('.bar-fill');
    
    const barObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const width = entry.target.style.width;
                entry.target.style.width = '0%';
                setTimeout(() => {
                    entry.target.style.width = width;
                }, 100);
                barObserver.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.5
    });
    
    bars.forEach(bar => {
        barObserver.observe(bar);
    });
    
    // Animate time chart bars
    const timeBars = document.querySelectorAll('.time-bar');
    
    const timeBarObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry, index) => {
            if (entry.isIntersecting) {
                setTimeout(() => {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'scaleX(1)';
                }, index * 150);
                timeBarObserver.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.5
    });
    
    timeBars.forEach(bar => {
        bar.style.opacity = '0';
        bar.style.transform = 'scaleX(0)';
        bar.style.transformOrigin = 'left';
        bar.style.transition = 'opacity 0.4s ease, transform 0.6s ease';
        timeBarObserver.observe(bar);
    });
}

// ========================================
// SUBSTEP TOOLTIPS
// ========================================
document.querySelectorAll('.substep').forEach(substep => {
    substep.addEventListener('mouseenter', () => {
        substep.style.transform = 'translateX(4px)';
    });
    
    substep.addEventListener('mouseleave', () => {
        substep.style.transform = 'translateX(0)';
    });
});

// ========================================
// FLOW NODE INTERACTIONS
// ========================================
document.querySelectorAll('.flow-node').forEach(node => {
    node.addEventListener('click', () => {
        // Add pulse animation
        node.style.animation = 'pulse 0.3s ease';
        setTimeout(() => {
            node.style.animation = '';
        }, 300);
    });
});

// Add pulse animation keyframes dynamically
const style = document.createElement('style');
style.textContent = `
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.05); }
        100% { transform: scale(1); }
    }
`;
document.head.appendChild(style);

// ========================================
// KEYBOARD NAVIGATION
// ========================================
document.addEventListener('keydown', (e) => {
    // Press 1, 2, 3 to toggle stages
    if (e.key === '1') toggleStage('discovery');
    if (e.key === '2') toggleStage('scrape');
    if (e.key === '3') toggleStage('profile');
    
    // Press Escape to close mobile sidebar
    if (e.key === 'Escape') {
        const sidebar = document.getElementById('sidebar');
        sidebar.classList.remove('open');
    }
});

// ========================================
// SEARCH FUNCTIONALITY (Future)
// ========================================
function searchDocs(query) {
    // Placeholder for future search functionality
    console.log('Searching for:', query);
}

// ========================================
// PRINT STYLES
// ========================================
window.addEventListener('beforeprint', () => {
    // Expand all stages for print
    document.querySelectorAll('.stage-content').forEach(c => {
        c.classList.add('expanded');
    });
    document.querySelectorAll('.schema-content').forEach(c => {
        c.classList.add('expanded');
    });
});

// ========================================
// CONSOLE LOG
// ========================================
console.log('%c🔍 Busca Fornecedor Docs v2.0', 'font-size: 20px; font-weight: bold; color: #3b82f6;');
console.log('%cDocumentação do Sistema de Construção de Perfis B2B', 'font-size: 12px; color: #9ca3af;');



