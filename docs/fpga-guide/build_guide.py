#!/usr/bin/env python3
"""
Build "Inside the bladeRF FPGA" — a single HTML page with a sticky chapter sidebar.

    python build_guide.py            # writes fpga-guide.out.html

Then publish that file with the Artifact tool, passing the URL in URLS['guide']
below so it updates in place instead of creating a new artifact.

To ADD A CHAPTER, see README.md in this directory. Short version: write
chN.frag.html containing only <section>...</section> blocks, then add one entry
to CHAPTERS below. Nothing else needs touching.
"""

import io
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'fpga-guide.out.html')

# --------------------------------------------------------------------------
# Published artifact URL. Pass this as `url` when republishing so the link
# stays stable. If you create a new artifact instead, update this.
# --------------------------------------------------------------------------
GUIDE_URL = 'https://claude.ai/code/artifact/cd0df1ad-2556-428f-a75a-1b02b4236619'

# --------------------------------------------------------------------------
# THE ONLY TABLE YOU NEED TO EDIT TO ADD A CHAPTER.
#
#   id       : anchor for the chapter divider, e.g. 'ch6'
#   num      : displayed chapter number, e.g. '06'
#   title    : chapter heading
#   dek      : one-paragraph summary under the heading
#   tally    : exactly 4 (value, label) pairs for the stat strip
#   frag     : filename holding the chapter's <section> blocks
#   prefix   : short unique letter used to build section ids (p1, p2, ...)
#   nav      : ONE LABEL PER <section> IN frag, in order. Must match the count
#              or the build aborts.
# --------------------------------------------------------------------------
CHAPTERS = [
    dict(
        id='ch1', num='01', title='The Module Inventory', frag='ch1.frag.html', prefix='m',
        dek='Every block compiled into the hosted image &mdash; what it is, where it came '
            'from, and the one thing it does. Grouped by the clock domain it lives in, '
            'because that is the real structure of this design.',
        tally=[('3', 'clock domains'), ('22', 'Qsys instances'),
               ('4', 'IP vendors'), ('5', 'dual-clock FIFOs')],
        nav=['Vendors vs. Qsys', 'How the fabric is organised', 'Clocking &amp; CDC',
             'Host interface', 'Sample datapath', 'The Qsys system', 'Not in this image'],
    ),
    dict(
        id='ch2', num='02', title='The Round Trip', frag='ch2.frag.html', prefix='r',
        dek='One sample, all the way out and all the way back: from a USB bulk transfer, '
            'across three clock domains, out of the antenna, and home again. Every module '
            'it touches, every wire it rides, and the cycle counts wherever the RTL '
            'commits to one.',
        tally=[('7', 'stages each way'), ('2048', 'words per transaction'),
               ('1022', 'FIFO ops per message'), ('3', 'domain crossings')],
        nav=['The map', 'Outbound: USB &#8594; antenna', 'The crossing (LVDS)',
             'Inbound: antenna &#8594; USB', 'What it costs'],
    ),
    dict(
        id='ch3', num='03', title='The NIOS', frag='ch3.frag.html', prefix='n',
        dek='The soft CPU that executes every host command: what it is, every pin and '
            'peripheral it reaches, everything it does &mdash; with a worked example of '
            'each &mdash; and the surprising answer to how it starts and how it is '
            'switched off.',
        tally=[('99', 'system ports'), ('19', 'bus slaves'),
               ('9', 'packet families'), ('0', 'lines of assembly')],
        nav=['What it is', 'Life and death', 'The pins', 'What it does',
             'Assembly &amp; toolchain', 'The VHDL it drives', 'Dead code &amp; defects'],
    ),
    dict(
        id='ch4', num='04', title='The TX FIFO', frag='ch4.frag.html', prefix='t',
        dek='The buffer between the USB bus and the radio clock, on the transmit side. '
            'What drives every port, what gates a write, and which of its flags are wired '
            'across the chip only to be ignored.',
        tally=[('32&#8594;64', 'bit widths'), ('32 KiB', 'storage'),
               ('6144', 'watermark, words'), ('4', 'flags never read')],
        nav=['What it is', 'The wiring', 'What gates a write', 'The trigger trick',
             'Wired but unread', 'Data provenance'],
    ),
    dict(
        id='ch5', num='05', title='The RX FIFO', frag='ch5.frag.html', prefix='x',
        dek='The mirror image on the receive side &mdash; and the three places it '
            'deliberately is not a mirror. Its occupancy count is what reaches back into '
            'bus arbitration and pre-empts transmit.',
        tally=[('64&#8594;32', 'bit widths'), ('64 KiB', 'storage'),
               ('2', 'waterlines'), ('3', 'sibling FIFOs')],
        nav=['What it is', 'The wiring', 'The two waterlines', 'The clear line',
             'Sibling FIFOs', 'Data provenance'],
    ),
    dict(
        id='ch6', num='06', title='The Sample Reader', frag='ch6.frag.html', prefix='d',
        dek='<code>fifo_reader</code> &mdash; what decides when to pop the TX FIFO, how a 64-bit word '
            'becomes per-channel samples, and why an idle transmitter is not a silent one.',
        tally=[('2', 'state machines'), ('1022', 'reads per message'),
               ('&plusmn;2047', 'silent truncation'), ('1', 'state unreachable')],
        nav=['What it is', 'Two machines, one licence', 'The three sample formats',
             'What one read serves',
             'The timestamp gate', 'Idle is not silent', 'Wired but unread'],
    ),
    dict(
        id='ch7', num='07', title='The Sample Packer', frag='ch7.frag.html', prefix='w',
        dek='<code>fifo_writer</code> &mdash; what packs RX samples into the FIFO, builds the '
            'metadata header, and why its credit check does nothing at all in the SFCW build.',
        tally=[('2', 'state machines'), ('128', 'bit header'),
               ('4', 'header slots reserved'), ('1', 'LED, no register')],
        nav=['What it is', 'Two machines, one interlock', 'How samples get packed',
             'The header it builds', 'The credit check', 'Overflow and dead code'],
    ),
]

# index.frag.html holds three <section>s: [0] chapter cards (unused here),
# [1] "findings at a glance", [2] "how this was made".
FRONT_SECTION = 1
BACK_SECTION = 2

LAYOUT_CSS = '''
/* ---- single-page layout ---- */
html { scroll-behavior: smooth; }
.layout { display: grid; grid-template-columns: 262px minmax(0,1fr); gap: 0 52px;
  max-width: 1250px; margin: 0 auto; padding: 0 28px; align-items: start; }
.side { position: sticky; top: 0; height: 100vh; overflow-y: auto; padding: 36px 0 48px; }
.brand { padding-bottom: 16px; margin-bottom: 10px; border-bottom: 1px solid var(--rule-2); }
.bt { display: block; font-family: var(--f-display); font-weight: 700; font-size: 17px;
  line-height: 1.2; letter-spacing: -.012em; color: var(--ink); }
.bs { display: block; font-family: var(--f-mono); font-size: 10.5px; color: var(--slate); margin-top: 6px; }
.side nav a { display: block; font-family: var(--f-display); font-size: 13px; line-height: 1.35;
  text-decoration: none; color: var(--ink-2); padding: 6px 0 6px 13px;
  border-left: 2px solid transparent; }
.side nav a:hover { color: var(--indigo); }
.side nav a.on { color: var(--indigo); border-left-color: var(--indigo); font-weight: 600; }
a.navch { font-family: var(--f-mono); font-size: 10.5px; font-weight: 700; letter-spacing: .14em;
  text-transform: uppercase; color: var(--slate); margin: 22px 0 4px; padding-left: 13px;
  border-left: 2px solid transparent; }
.main { min-width: 0; padding-bottom: 110px; }
section[id], .chapdiv { scroll-margin-top: 18px; }
@media (max-width: 940px) {
  .layout { grid-template-columns: minmax(0,1fr); gap: 0; }
  .side { position: static; height: auto; padding: 24px 0 16px;
    border-bottom: 1px solid var(--rule-2); }
  .side nav { display: flex; flex-wrap: wrap; gap: 5px; }
  .side nav a { border-left: none; border: 1px solid var(--rule-2); border-radius: 2px; padding: 5px 9px; }
  .side nav a.on { border-color: var(--indigo); }
  .side nav a.navch { width: 100%; margin: 14px 0 2px; padding-left: 0; border: none; }
}
@media print {
  .side { display: none; }
  .layout { grid-template-columns: 1fr; max-width: none; }
  figure, .note, .mod, tr { break-inside: avoid; }
  .chapdiv { break-before: page; }
}
</style>'''

SCROLLSPY = '''
<script>
(function () {
  var targets = [].slice.call(document.querySelectorAll('[data-nav], .chapdiv[id]'));
  var links = {};
  [].forEach.call(document.querySelectorAll('.side nav a[href^="#"]'), function (a) {
    var id = a.getAttribute('href').slice(1);
    if (!links[id]) { links[id] = []; }
    links[id].push(a);
  });
  var all = [].slice.call(document.querySelectorAll('.side nav a'));
  function update() {
    var cur = targets[0], i;
    for (i = 0; i < targets.length; i++) {
      if (targets[i].getBoundingClientRect().top <= 140) { cur = targets[i]; }
    }
    all.forEach(function (a) { a.classList.remove('on'); });
    var set = cur && links[cur.id];
    if (set) { set.forEach(function (a) { a.classList.add('on'); }); }
  }
  var ticking = false;
  function onScroll() {
    if (ticking) { return; }
    ticking = true;
    requestAnimationFrame(function () { update(); ticking = false; });
  }
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
  update();
})();
</script>
'''


def read(name):
    with io.open(os.path.join(HERE, name), encoding='utf-8') as f:
        return f.read()


def sections(text):
    """Chapter fragments contain ONLY top-level <section>...</section> blocks."""
    return re.findall(r'<section>.*?</section>', text, re.S)


def tally_html(pairs):
    rows = ''.join('    <div><b>%s</b><span>%s</span></div>\n' % p for p in pairs)
    return '  <div class="tally">\n%s  </div>\n' % rows


def main():
    head = read('base-head.html')
    idx = sections(read('index.frag.html'))
    front = idx[FRONT_SECTION].replace('<section>', '<section id="findings" data-nav>', 1)
    back = idx[BACK_SECTION].replace('<section>', '<section id="method" data-nav>', 1)

    nav = ['<a class="navch" href="#findings">Overview</a>',
           '<a href="#findings">Findings at a glance</a>']
    body = [front]

    for ch in CHAPTERS:
        secs = sections(read(ch['frag']))
        if len(secs) != len(ch['nav']):
            raise SystemExit(
                'ABORT: %s has %d <section> blocks but %d nav labels. '
                'They must match 1:1, in order.' % (ch['frag'], len(secs), len(ch['nav'])))
        ids = ['%s%d' % (ch['prefix'], i + 1) for i in range(len(secs))]

        nav.append('<a class="navch" href="#%s">Chapter %s &#183; %s</a>'
                   % (ch['id'], ch['num'], ch['title']))
        nav += ['<a href="#%s">%s</a>' % (i, t) for i, t in zip(ids, ch['nav'])]

        body.append(
            '\n<div class="chapdiv" id="%s">\n  <p class="n">Chapter %s</p>\n'
            '  <h2>%s</h2>\n  <p class="dek">%s</p>\n%s</div>\n\n'
            % (ch['id'], ch['num'], ch['title'], ch['dek'], tally_html(ch['tally'])))
        body += [s.replace('<section>', '<section id="%s" data-nav>' % i, 1)
                 for s, i in zip(secs, ids)]

    nav += ['<a class="navch" href="#method">Appendix</a>',
            '<a href="#method">How this was made</a>']
    body.append(back)

    page = (
        '<title>Inside the bladeRF FPGA</title>\n' + head + LAYOUT_CSS + '''

<div class="layout">

<aside class="side">
  <div class="brand">
    <span class="bt">Inside the<br>bladeRF FPGA</span>
    <span class="bs">hosted image &#183; 35174c30</span>
  </div>
  <nav>
      ''' + '\n      '.join(nav) + '''
  </nav>
</aside>

<main class="main">

<header class="mast">
  <p class="chapno">A working guide &#183; bladeRF 2.0 micro</p>
  <h1>Inside the bladeRF FPGA</h1>
  <p class="chaptitle">What is in the bitstream, and what a sample does in it</p>
  <p class="dek">Every claim here is read out of the RTL, the build manifests and the FX3
  firmware &mdash; not from documentation, and not from memory. Where the source could not
  settle a question, it says so.</p>
''' + tally_html([('%d' % len(CHAPTERS), 'chapters'), ('35174c30', 'source revision'),
                  ('0.16.0', 'NIOS FPGA'), ('0', 'measured on hardware')]) + '''</header>
''' + ''.join(body) + '''
<footer class="foot">
  <p>
    <b>Inside the bladeRF FPGA</b> &#183; a working guide to the hosted image on the bladeRF 2.0 micro.<br>
    Traced from the VHDL, Verilog, FX3 firmware and build manifests at revision 35174c30.
    Cycle counts are read out of the state machines; clock rates are derived from the
    constraints and the deserializer geometry. Nothing here is measured on hardware.
  </p>
</footer>

</main>
</div>
''' + SCROLLSPY)

    with io.open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(page)

    # sanity checks — a malformed page publishes silently, so fail loud here
    problems = []
    for tag in ('div', 'section', 'figure', 'table', 'svg', 'p', 'g', 'a',
                'span', 'header', 'footer', 'aside', 'main', 'nav', 'script',
                'pre', 'ul', 'li', 'tbody', 'thead', 'tr'):
        o = len(re.findall(r'<%s[ >]' % tag, page))
        c = len(re.findall(r'</%s>' % tag, page))
        if o != c:
            problems.append('%s open=%d close=%d' % (tag, o, c))
    for m in re.findall(r'<(?:rect|line|path|circle|polyline)\b[^>]*>', page):
        if not m.rstrip().endswith('/>'):
            problems.append('unclosed SVG shape: ' + m[:60])
            break

    print('%s  %d chars  %d chapters  %d sections  %d nav links'
          % (os.path.basename(OUT), len(page), len(CHAPTERS),
             len(re.findall(r'<section id=', page)),
             len(re.findall(r'<a [^>]*href="#', page))))
    if problems:
        raise SystemExit('MALFORMED:\n  ' + '\n  '.join(problems))
    print('OK. Publish with the Artifact tool, url=' + GUIDE_URL)


if __name__ == '__main__':
    main()
