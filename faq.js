/* ═══════════════════════════════════════════════════════════════════════
   Gather — In-App FAQ View
   Renders an accordion FAQ inside the main container.
   ═══════════════════════════════════════════════════════════════════════ */

const FAQ_DATA = [
    { group: 'Stitching Modes', items: [
        { q: "What's the difference between Fast Stitch and Polished Stitch?",
          a: '<p>Gather gives you two ways to combine your clips:</p>'
            + '<div class="faq-compare">'
            + '<div class="faq-cmp-card"><h4>\u26A1 Fast Stitch</h4><ul>'
            + '<li>Combines your clips <strong>almost instantly</strong></li>'
            + '<li>Dates appear as <strong>captions</strong> you can turn on or off</li>'
            + '<li>No quality loss at all</li>'
            + '</ul></div>'
            + '<div class="faq-cmp-card"><h4>\uD83C\uDFAC Polished Stitch</h4><ul>'
            + '<li>Takes a bit longer to process</li>'
            + '<li>Dates are <strong>permanently part of the video</strong></li>'
            + '<li>Visible everywhere \u2014 TVs, YouTube, social media</li>'
            + '</ul></div>'
            + '</div>'
            + '<p><strong>In short:</strong> Fast Stitch is instant and the dates work like subtitles you can toggle. Polished Stitch takes longer but bakes the dates right into the video so they show up no matter where you watch it.</p>',
          open: true },
        { q: 'Which mode should I pick?',
          a: '<p>For most people, <strong>Fast Stitch</strong> is all you need \u2014 it\u2019s the default for a reason. Pick <strong>Polished Stitch</strong> if you\u2019re planning to upload to YouTube, share on social media, or watch on a TV that might not display captions.</p>' },
        { q: 'Can I mix clips from different phones or cameras?',
          a: '<p>Absolutely! Throw in iPhone clips, GoPro footage, and old camcorder files all in the same project. Gather sorts out the differences automatically and makes them play together seamlessly.</p>' },
    ]},
    { group: 'General', items: [
        { q: 'What is Gather?',
          a: '<p>Gather turns your scattered phone clips and camera footage into one beautiful home video. Drop your clips in, hit stitch, and you\u2019ve got a real movie \u2014 with date stamps, a thumbnail, and easy uploads to YouTube or Google Drive.</p><p>Think of it as the missing step between \u201CI have 47 clips from vacation\u201D and \u201CWe have a movie to watch on the couch.\u201D</p>' },
        { q: 'How much does it cost?',
          a: '<p><strong>$9.99 \u2014 one time, yours forever.</strong> No subscriptions, no recurring charges, no \u201Cpremium tiers.\u201D Pay once, get the full app.</p>' },
        { q: 'What platforms does it run on?',
          a: '<p><strong>Mac</strong>, <strong>Windows</strong>, and <strong>Linux</strong>. Gather takes advantage of your computer\u2019s hardware to keep stitching fast on all three.</p>' },
        { q: 'Does it need an internet connection?',
          a: '<p>Nope! Gather works <strong>completely offline</strong>. Your videos never leave your computer unless you choose to upload them to YouTube or Google Drive.</p>' },
        { q: 'What video formats can I use?',
          a: '<p>Pretty much anything \u2014 <strong>MP4, MOV, MKV, AVI</strong>, and more. If your phone or camera recorded it, Gather can handle it.</p>' },
        { q: 'Does Gather collect any of my data?',
          a: '<p><strong>No.</strong> No accounts, no tracking, no analytics. Gather doesn\u2019t upload anything unless you explicitly ask it to. Your family videos are your business.</p>' },
    ]},
    { group: 'Features', items: [
        { q: 'How do date stamps work?',
          a: '<p>Gather automatically reads the date each clip was recorded and displays it on screen \u2014 like \u201CMarch 14, 2025.\u201D You don\u2019t need to do anything; it just picks up the info from your video files.</p>' },
        { q: 'Can I choose my own thumbnail?',
          a: '<p>Yes! After stitching, Gather shows you a few frame options from your video. Pick the one you like, or shuffle for more choices. That\u2019s the image that shows up in your library.</p>' },
        { q: 'Can I upload to YouTube or Google Drive?',
          a: '<p>Yep \u2014 one click for each. Set a title and privacy level for YouTube, or just a title for Drive, and you\u2019re done. No extra apps needed.</p>' },
        { q: 'Can I cancel stitching if I change my mind?',
          a: '<p>Of course. Hit \u201CCancel Stitching\u201D anytime and Gather stops cleanly \u2014 no leftover junk or half-finished files.</p>' },
    ]},
];

function showFaq() {
    const $ = id => document.getElementById(id);

    $('uploadView').style.display = 'none';
    if ($('yView')) $('yView').remove();
    if ($('faqView')) $('faqView').remove();

    document.querySelectorAll('.year-link').forEach(l => l.classList.remove('active'));
    const faqLink = document.querySelector('.sidebar [onclick="showFaq()"]');
    if (faqLink) faqLink.classList.add('active');

    const view = document.createElement('div');
    view.id = 'faqView';
    view.className = 'faq-view';

    const h1 = document.createElement('h1');
    h1.style.cssText = 'font-family:Playball,cursive; color:var(--primary-hover); font-weight:400';
    h1.textContent = 'FAQs';
    view.appendChild(h1);

    const sub = document.createElement('p');
    sub.className = 'faq-sub';
    sub.textContent = 'Everything you need to know about Gather';
    view.appendChild(sub);

    FAQ_DATA.forEach(group => {
        const section = document.createElement('div');
        section.className = 'faq-group';

        const h2 = document.createElement('h2');
        h2.textContent = group.group;
        section.appendChild(h2);

        group.items.forEach(item => {
            const card = document.createElement('div');
            card.className = 'faq-card' + (item.open ? ' open' : '');

            const btn = document.createElement('button');
            btn.className = 'faq-q';
            const qSpan = document.createElement('span');
            qSpan.textContent = item.q;
            const chevron = document.createElement('span');
            chevron.className = 'chevron';
            chevron.textContent = '\u25BC';
            btn.append(qSpan, chevron);

            btn.onclick = () => {
                const wasOpen = card.classList.contains('open');
                section.querySelectorAll('.faq-card.open').forEach(c => c.classList.remove('open'));
                if (!wasOpen) card.classList.add('open');
            };

            const ans = document.createElement('div');
            ans.className = 'faq-a';
            const inner = document.createElement('div');
            inner.className = 'faq-a-inner';
            inner.innerHTML = item.a;
            ans.appendChild(inner);

            card.append(btn, ans);
            section.appendChild(card);
        });

        view.appendChild(section);
    });

    $('mainContent').appendChild(view);
}
