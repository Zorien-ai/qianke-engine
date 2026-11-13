import test from "node:test";
import assert from "node:assert/strict";
import { productMatchesQuery, catalogQueryTerms } from "../src/catalogSearch.js";

const tea = { title: "明前龙井", category: "绿茶", brand: "山雾", skus: [{ spec: "250g 礼盒" }] };
const puerh = { title: "云南普洱熟茶", category: "普洱茶", brand: "山雾", skus: [{ spec: "357g 饼" }] };
const shoe = { title: "轻量跑鞋", category: "运动", brand: "峰行", skus: [{ spec: "标准" }] };

test("broad tea query matches real tea categories", () => {
  assert.equal(productMatchesQuery(tea, "茶叶"), true);
  assert.equal(productMatchesQuery(puerh, "茶叶"), true);
  assert.equal(productMatchesQuery(shoe, "茶叶"), false);
});

test("green tea query and specific tea title", () => {
  assert.equal(productMatchesQuery(tea, "绿茶"), true);
  assert.equal(productMatchesQuery(tea, "龙井"), true);
  assert.equal(productMatchesQuery(puerh, "绿茶"), false);
});

test("gear query stays in gear catalog", () => {
  assert.equal(productMatchesQuery(shoe, "跑鞋"), true);
  assert.equal(productMatchesQuery(shoe, "户外"), false);
});

test("generic browse query still accepts products", () => {
  assert.equal(productMatchesQuery(tea, ""), true);
  assert.equal(productMatchesQuery(tea, "全部商品"), true);
  assert.ok(catalogQueryTerms("茶叶").has("茶"));
});
