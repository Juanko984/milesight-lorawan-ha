// usage: node run_official_encoder.js encoder.js '[{payload}, ...]' -> JSON list of hex strings
const fs = require('fs'), vm = require('vm');
const ctx = {console}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const inputs = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
console.log(JSON.stringify(inputs.map(p => {
  try { return Buffer.from(ctx.milesightDeviceEncode(p)).toString('hex'); } catch (e) { return "ERR " + e; }
})));
