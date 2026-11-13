import test from "node:test";
import assert from "node:assert/strict";
import { createCartStore, CART_STORAGE_KEY, cartCheckoutPayload, cartItemKey, cartTotal } from "../src/cart.js";

const tea = (extra = {}) => ({ friend_id: "store_tea", merchant_name: "茶店", product_id: "tea-1", sku: "tea-50g", spec: "50g", title: "龙井", price: 68, stock: 53, quantity: 2, ...extra });
function setup(initial = []) {
  const values = new Map([[CART_STORAGE_KEY, JSON.stringify(initial)]]);
  const storage = { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  const events = new EventTarget();
  const cart = createCartStore(storage, events);
  const stored = () => JSON.parse(storage.getItem(CART_STORAGE_KEY));
  const externalWrite = (value) => {
    storage.setItem(CART_STORAGE_KEY, value);
    const event = new Event("storage");
    Object.assign(event, { key: CART_STORAGE_KEY, newValue: value, storageArea: storage });
    events.dispatchEvent(event);
  };
  return { cart, storage, stored, externalWrite };
}

test("existing CApp carts load without a migration; invalid lines are ignored", () => {
  const { cart } = setup([tea(), null, {}, tea({ sku: "bad", quantity: 1.5 })]);
  assert.equal(cart.items.value.length, 1);
  assert.deepEqual({ ...cart.items.value[0] }, { ...tea(), image_url: "" });
});

test("add, quantity edit and SKU edit persist the exact shared cart", () => {
  const { cart, stored } = setup();
  cart.add(tea());
  cart.setQuantity(tea(), 3);
  cart.edit(tea(), { sku: "tea-250g", spec: "250g", price: 298, stock: 4 }, 2);
  assert.equal(stored()[0].sku, "tea-250g");
  assert.equal(stored()[0].quantity, 2);
  assert.equal(stored()[0].price, 298);
  assert.equal(cartTotal(cart.items.value), 596);
  const otherRoute = createCartStore({ getItem: () => JSON.stringify(stored()) });
  assert.deepEqual(otherRoute.items.value, cart.items.value);
});

test("SKU merge refreshes price and inventory and respects stock / 20-item cap", () => {
  const { cart } = setup([tea(), tea({ sku: "tea-250g", quantity: 5, price: 200, stock: 100 })]);
  cart.edit(tea(), { sku: "tea-250g", spec: "250g", price: 298, stock: 6 }, 3);
  assert.equal(cart.items.value.length, 1);
  assert.equal(cart.items.value[0].quantity, 6);
  assert.equal(cart.items.value[0].price, 298);
  cart.add(tea({ sku: "tea-250g", quantity: 20, stock: 100 }));
  assert.equal(cart.items.value[0].quantity, 20);
});

test("identical SKU text in different shops never removes or updates the other shop", () => {
  const other = tea({ friend_id: "other_shop" });
  const { cart } = setup([tea(), other]);
  assert.notEqual(cartItemKey(tea()), cartItemKey(other));
  cart.setQuantity(tea(), 4);
  assert.equal(cart.items.value[1].quantity, 2);
  cart.remove(tea());
  assert.equal(cart.items.value.length, 1);
  assert.equal(cart.items.value[0].friend_id, "other_shop");
});

test("sold-out SKU edits and edits to a removed line are rejected", () => {
  const { cart } = setup([tea()]);
  assert.throws(() => cart.edit(tea(), { sku: "soldout", stock: 0 }, 1), /缺货/);
  assert.throws(() => cart.edit(tea(), { sku: "new", stock: 5 }, 1.5), /整数/);
  assert.throws(() => cart.edit(tea(), { sku: "new", stock: 5 }, 0), /整数/);
  cart.remove(tea());
  assert.throws(() => cart.edit(tea(), { sku: "new", stock: 5 }, 1), /已变化/);
});

test("storage events update another tab without writing back; malformed events are ignored", () => {
  const { cart, externalWrite } = setup([tea()]);
  externalWrite(JSON.stringify([tea({ sku: "tea-250g", quantity: 3 })]));
  assert.equal(cart.items.value[0].sku, "tea-250g");
  assert.equal(cart.items.value[0].quantity, 3);
  externalWrite("not json");
  assert.equal(cart.items.value.length, 1);
  externalWrite("[]");
  assert.equal(cart.items.value.length, 0);
});

test("storage failures retain a usable shared in-memory cart", () => {
  const cart = createCartStore({ getItem() { throw Error("denied"); }, setItem() { throw Error("denied"); } });
  cart.add(tea());
  cart.reload();
  assert.equal(cart.items.value.length, 1);
});

test("checkout sends only exact SKU / quantity items and keeps the cart intact", () => {
  const { cart } = setup([tea(), tea({ sku: "tea-other", quantity: 1 })]);
  assert.deepEqual(cartCheckoutPayload(cart.items.value), { friend_id: "store_tea", items: [{ sku: "tea-50g", quantity: 2 }, { sku: "tea-other", quantity: 1 }] });
  assert.equal(cart.items.value.length, 2);
  assert.throws(() => cartCheckoutPayload([tea(), tea({ friend_id: "other" })]), /分别/);
  assert.throws(() => cartCheckoutPayload(Array.from({ length: 11 }, (_, i) => tea({ sku: `sku-${i}` }))), /10/);
  assert.throws(() => cartCheckoutPayload([tea({ quantity: 1.5 })]), /整数/);
});

test("drafts / failures / cancellations do not consume the cart; confirmed items do", () => {
  const { cart, stored } = setup([tea()]);
  const quote = { friend_id: "store_tea" };
  for (const status of ["DRAFT", "PENDING", "CANCELLED", "FAILED"]) cart.consumeOrder(quote, { status, items: [tea()] });
  assert.equal(cart.items.value.length, 1);
  cart.consumeOrder(quote, { status: "CONFIRMED", items: [tea()] });
  assert.deepEqual(stored(), []);
});

test("confirmation removes purchased quantities only, preserving later additions / other shops / new specs", () => {
  const { cart } = setup([tea({ quantity: 4 }), tea({ friend_id: "other_shop" }), tea({ sku: "new-spec" })]);
  cart.consumeOrder({ friend_id: "store_tea" }, { status: "CONFIRMED", items: [tea({ quantity: 2 })] });
  assert.equal(cart.items.value[0].quantity, 2);
  assert.equal(cart.items.value.length, 3);
});

test("currency totals use integer cents", () => {
  assert.equal(cartTotal([tea({ price: 0.1, quantity: 1 }), tea({ price: 0.2, quantity: 1 })]), 0.3);
});

test("HTTP order items without SKU consume only an exactly matching confirmed quote", () => {
  const { cart } = setup([tea(), tea({ sku: "tea-250g", price: 298, quantity: 1 })]);
  const refs = [tea(), tea({ sku: "tea-250g", price: 298, quantity: 1 })];
  const quote = { quote_id: "quote-1", friend_id: "store_tea", product_refs: refs };
  const order = { quote_id: "quote-1", status: "CONFIRMED", items: refs.map(({ product_id, price, quantity }) => ({ product_id, unit_price: price, quantity })) };
  cart.consumeOrder(quote, { ...order, quote_id: "another-quote" });
  assert.equal(cart.items.value.length, 2);
  cart.consumeOrder(quote, { ...order, items: [{ product_id: "tea-1", unit_price: 68, quantity: 1 }] });
  assert.equal(cart.items.value.length, 2);
  cart.consumeOrder(quote, order);
  assert.deepEqual(cart.items.value, []);
});
