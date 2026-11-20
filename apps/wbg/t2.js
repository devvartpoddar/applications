const L=require('./lib.js');
(async()=>{const p=await L.open();await L.enter(p);await L.nav(p,'Explore');await L.settle(p,2000);await L.bad(p,'country');await L.shot(p,'country');
const v=await p.$$eval('#pick option',o=>o.map(x=>x.value+'|'+x.textContent));console.log(v.slice(0,40));console.log(p.errs);await p.b.close()})();
