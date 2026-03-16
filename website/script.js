/* ═══════════════════════════════════════════════════════════════════════
   Gather — Marketing Site Scripts
   Minimal, vanilla JS. No frameworks needed for a landing page.
   ═══════════════════════════════════════════════════════════════════════ */

(() => {
    'use strict';

    /* ─── Nav scroll shadow ─────────────────────────────────────────── */
    const nav = document.querySelector('.nav');
    const onScroll = () => {
        nav.classList.toggle('scrolled', window.scrollY > 10);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();

    /* ─── Mobile menu toggle ────────────────────────────────────────── */
    const toggle = document.querySelector('.nav-toggle');
    const links  = document.querySelector('.nav-links');

    toggle.addEventListener('click', () => {
        links.classList.toggle('open');
    });

    // Close mobile menu when a link is clicked
    links.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => links.classList.remove('open'));
    });

    /* ─── Scroll-triggered fade-in animations ───────────────────────── */
    const animatedElements = document.querySelectorAll(
        '.feature-card, .step, .showcase-text, .showcase-visual, .download-card'
    );

    // Add the fade-in class to all targets
    animatedElements.forEach(el => el.classList.add('fade-in'));

    const observer = new IntersectionObserver(
        (entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible');
                    observer.unobserve(entry.target);
                }
            });
        },
        { threshold: 0.15, rootMargin: '0px 0px -40px 0px' }
    );

    animatedElements.forEach(el => observer.observe(el));

    /* ─── Staggered animation delays for grids ──────────────────────── */
    document.querySelectorAll('.feature-card').forEach((card, i) => {
        card.style.transitionDelay = `${i * 0.08}s`;
    });

    /* -- Memory card: play video on hover ------------------------ */
    document.querySelectorAll('.memory-card').forEach(card => {
        const video = card.querySelector('video');
        if (!video) return;

        card.addEventListener('mouseenter', () => {
            video.currentTime = 0;
            video.play().catch(() => {});
        });

        card.addEventListener('mouseleave', () => {
            video.pause();
            video.currentTime = 0;
        });
    });

    document.querySelectorAll('.step').forEach((step, i) => {
        step.style.transitionDelay = `${i * 0.12}s`;
    });

    document.querySelectorAll('.memory-card').forEach((card, i) => {
        card.style.transitionDelay = `${i * 0.1}s`;
    });

    /* ─── Smooth scroll for anchor links (fallback for older Safari) ── */
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', (e) => {
            const target = document.querySelector(anchor.getAttribute('href'));
            if (!target) return;
            e.preventDefault();
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
    });
})();
