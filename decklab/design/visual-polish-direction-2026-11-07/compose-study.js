'use strict';
// Proposal-only composition of the current disposable DOM. Original nodes stay.
module.exports = function composeStudy(receipt) {
  document.documentElement.classList.add('design-composed');
  const details = (label, nodes) => {
    const d=document.createElement('details'); d.className='study-details';
    const s=document.createElement('summary'); s.textContent=label; d.append(s);
    for(const node of nodes.filter(Boolean)) d.append(node);
    return d;
  };
  if(receipt) {
    const head=document.querySelector('.rcpt-page-head');
    const grid=head.querySelector('.rcpt-head-grid');
    const title=grid.querySelector('.page-head');
    head.insertBefore(title,grid);
    const context=details('Order details',[grid,document.querySelector('.rcpt-notes'),document.querySelector('.rcpt-more')]);
    const tools=document.createElement('div');tools.className='study-order-tools';
    const bulk=document.querySelector('.rcpt-everything-bar');
    tools.append(context);if(bulk) tools.append(bulk);head.append(tools);
    for(const section of document.querySelectorAll('.rcpt-section')) {
      const body=section.querySelector('.rcpt-body');
      const generic=body.querySelector(':scope > p.sub');
      const blank=body.querySelector('.rcpt-all-blank');
      if(generic||blank) section.querySelector('.rcpt-section-head').append(details('Checking help',[generic,blank]));
      const heading=section.querySelector('.rcpt-section-head h2');
      const short=heading.textContent.match(/^\d+ (?:cards?|token cards?)/);
      if(short) {
        heading.classList.add('sr-only');
        const visible=document.createElement('div');visible.className='study-board-title';
        visible.setAttribute('aria-hidden','true');visible.textContent=short[0];heading.after(visible);
      }
    }
    const bar=document.querySelector('.rcpt-bar');
    const progress=document.createElement('div');progress.className='study-progress';
    progress.append(bar.querySelector('.rcpt-status-line'),bar.querySelector('.rcpt-blanks'));
    bar.prepend(progress);
  } else {
    const description=document.querySelector('.page-head p');
    const board=document.querySelector('.gb-board');
    const notes=[...board.querySelectorAll(':scope > .gb-note')];
    const about=details('About these results',[description,...notes]);
    const intro=board.querySelector('.gb-intro');
    const count=intro.textContent.match(/same (\d+) popular/);
    if(!count||!notes.some(n=>n.textContent.includes('one against one'))) throw new Error('Study requires its explicit synthetic sample and 1v1 scope');
    const format=document.querySelector('.mu-format [aria-pressed="true"]')?.textContent.trim()||'Commander';
    const scope=document.createElement('p');scope.className='study-scope';
    scope.textContent=`${format} · 1v1 · ${count[1]} sampled opponents · Win rate, not a rating`;
    board.prepend(scope);scope.after(about);about.insertBefore(intro,about.children[1]||null);
    const results=document.querySelector('.mu-home-head h2');
    results.classList.add('sr-only');
    // Keep the existing action and handler; demote pairing on the Popular view.
    const pair=[...document.querySelectorAll('.page-head button')].find(n=>n.textContent.trim()==='Play a matchup');
    pair?.classList.remove('btn-primary');
    pair?.classList.add('btn-quiet');
    for(const button of document.querySelectorAll('.page-head button.btn')) button.classList.add('btn-quiet');
  }
};
