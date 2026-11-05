'use strict';
// Open the same disclosures a user needs to reach moved Explorer controls.
// Keep interaction through their native summaries (no force clicks / hidden inputs).
async function revealControl(page, selector) {
  const control = page.locator(selector).first();
  const parentPanel = await control.evaluate(element => element.closest('#analysis-filter-panel, #analysis-tools')?.id);
  if (parentPanel !== 'analysis-filter-panel') await closeFilters(page);
  if (parentPanel !== 'analysis-tools') await closeTools(page);
  const ancestors = await control.locator('xpath=ancestor::details').all();
  if (await control.evaluate(element => element.tagName === 'SUMMARY')) ancestors.pop();
  for (const ancestor of ancestors) {
    if (!(await ancestor.evaluate(element => element.open))) await ancestor.locator(':scope > summary').click();
  }
}
async function openFilters(page) {
  await closeTools(page);
  const panel = page.locator('#analysis-filter-panel');
  if (await panel.count() && !(await panel.evaluate(element => element.open))) await panel.locator(':scope > summary').click();
}
async function closeFilters(page) {
  const panel = page.locator('#analysis-filter-panel');
  if (await panel.count() && await panel.evaluate(element => element.open)) await panel.locator(':scope > summary').click();
}
async function openTools(page) {
  await closeFilters(page);
  const panel = page.locator('#analysis-tools');
  if (await panel.count() && !(await panel.evaluate(element => element.open))) await panel.locator(':scope > summary').click();
}
async function closeTools(page) {
  const panel = page.locator('#analysis-tools');
  if (await panel.count() && await panel.evaluate(element => element.open)) await panel.locator(':scope > summary').click();
}
async function history24h(page) {
  await page.locator('#analysis-time-preset').selectOption('24h');
}
module.exports = {revealControl, openFilters, closeFilters, openTools, closeTools, history24h};
