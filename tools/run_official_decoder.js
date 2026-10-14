// usage: node run.js decoder.js '[[hexpayload],...]'  -> JSON list of decoded objects
const fs = require('fs'), vm = require('vm');
const ctx = {console}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const inputs = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = inputs.map(h => {
  const bytes = Array.from(Buffer.from(h, 'hex'));
  try { return ctx.milesightDeviceDecode(bytes); } catch (e) { return {__error: String(e)}; }
});
console.log(JSON.stringify(out));
