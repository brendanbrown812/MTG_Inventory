const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');

// Use the existing TypeScript dependency; no browser or test packages needed.
const source = readFileSync(join(__dirname, '../src/lib/guestPrintings.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const helpers = {};
new Function('exports', compiled)(helpers);
const { collectionGuestPrintings, deckGuestPrintings } = helpers;
const base = { scryfall_id: 'original', name: 'Sol Ring', image_uri_normal: 'original.jpg', set_code: 'cmm', collector_number: '396' };
const alternate = { ...base, scryfall_id: 'alternate', image_uri_normal: 'alternate.jpg', set_code: 'sld', collector_number: '123' };
const row = (allocations) => ({ card: base, scryfall_id: base.scryfall_id, quantity: 4, allocations });
const allocation = (overrides = {}) => ({ scryfall_id: alternate.scryfall_id, printing: alternate, quantity: 1, foil: true, status: 'grabbed', ...overrides });

test('collection gallery retains each owned printing, artwork, quantity and treatment', () => {
  const printings = [base, alternate].map((card, index) => ({
    card, scryfall_id: card.scryfall_id, image_uri_normal: card.image_uri_normal,
    set_code: card.set_code, collector_number: card.collector_number,
    total_quantity: index + 1, foil_quantity: index, nonfoil_quantity: 1,
  }));
  const result = collectionGuestPrintings({ printings });
  assert.deepEqual(result.map((item) => item.image), ['original.jpg', 'alternate.jpg']);
  assert.equal(result[1].quantity, 2);
  assert.equal(result[1].treatment, '1 foil · 1 nonfoil');
});

test('deck uses allocated printing artwork instead of the base card and keeps foil variants separate', () => {
  const result = deckGuestPrintings(row([
    allocation(), allocation({ status: 'pending' }), allocation({ foil: false, quantity: 2 }),
  ]));
  assert.equal(result.length, 2);
  assert.ok(result.every((item) => item.image === 'alternate.jpg' && item.setCode === 'sld'));
  assert.equal(result[0].quantity, 2);
  assert.equal(result[0].treatment, 'Foil');
  assert.equal(result[1].quantity, 2);
  assert.equal(result[1].treatment, 'Nonfoil');
});

test('an unavailable exact printing never shows unrelated artwork', () => {
  const [result] = deckGuestPrintings(row([allocation({ printing: null })]));
  assert.equal(result.image, null);
  assert.equal(result.description, 'Assigned printing unavailable');
});

test('any-printing copies are labelled as examples while known prints remain exact', () => {
  const [any] = deckGuestPrintings(row([allocation({ scryfall_id: null, printing: null })]));
  assert.equal(any.image, 'original.jpg');
  assert.equal(any.description, 'Any printing · example artwork');
  const [known] = deckGuestPrintings(row([allocation({ scryfall_id: base.scryfall_id, printing: null })]));
  assert.equal(known.image, 'original.jpg');
  assert.equal(known.description, undefined);
  assert.equal(deckGuestPrintings(row([]))[0].quantity, 4);
});
