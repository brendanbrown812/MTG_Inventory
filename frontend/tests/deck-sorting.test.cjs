const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const ts = require('typescript');
const source = readFileSync(join(__dirname, '../src/lib/deckSorting.ts'), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const helpers = {};
new Function('exports', compiled)(helpers);
const { compareDeckCards, cardTypeCategory } = helpers;
const card = (name, overrides = {}) => ({ name, colors: '', cmc: 1, mana_cost: '{1}', type_line: 'Artifact', ...overrides });
const sorted = (cards, mode) => [...cards].sort((a, b) => compareDeckCards(a, b, mode)).map((card) => card.name);

test('shared admin and guest alphabetical sort ignores mana value and color', () => {
  assert.deepEqual(sorted([card('Zebra', { cmc: 0 }), card('Alpha', { cmc: 9 }), card('Beta')], 'name'), ['Alpha', 'Beta', 'Zebra']);
});

test('card type groups follow admin categories, mana value, variable mana, then name', () => {
  const cards = [card('Land', { type_line: 'Land' }), card('X artifact', { cmc: 0, mana_cost: '{X}' }), card('Zero artifact', { cmc: 0 }), card('Creature', { type_line: 'Artifact Creature' }), card('Commander', { type_line: 'Legendary Creature — Wizard' }), card('Instant', { type_line: 'Instant' }), card('A artifact')];
  assert.deepEqual(sorted(cards, 'type'), ['Commander', 'Creature', 'Instant', 'Zero artifact', 'A artifact', 'X artifact', 'Land']);
  assert.equal(cardTypeCategory(null), 'Other');
});

test('WUBRG sort supports stored JSON and comma-separated colors before multicolor and colorless', () => {
  const cards = [card('Colorless'), card('Multicolor', { colors: 'W,U' }), card('Green', { colors: '["G"]' }), card('Red', { colors: 'R' }), card('Black', { colors: 'B' }), card('Blue', { colors: '["U"]' }), card('White', { colors: 'W' })];
  assert.deepEqual(sorted(cards, 'color'), ['White', 'Blue', 'Black', 'Red', 'Green', 'Multicolor', 'Colorless']);
});
