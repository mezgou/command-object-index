const query = document.querySelector('#query');
const error = document.querySelector('#error');
const algorithmOptions = document.querySelector('#algorithm-options');
const algorithmCounter = document.querySelector('#algorithm-counter');
const algorithmResults = document.querySelector('#algorithm-results');
const resultCount = document.querySelector('#result-count');
const libraryList = document.querySelector('#library-list');
const libraryCount = document.querySelector('#count');
const addForm = document.querySelector('#add-form');
let catalog = [];
let algorithms = [];
let searchSequence = 0;
const DECISIONS = {accept: 'УВЕРЕННЫЙ ВЫБОР', clarify: 'НУЖНО УТОЧНЕНИЕ', reject: 'БЕЗОПАСНЫЙ ОТКАЗ'};
const STATUSES = {resolved: 'выбрано', ambiguous: 'неоднозначно', incomplete: 'неполная команда', incompatible: 'не сочетается', not_found: 'не найдено', negated: 'отрицание', unsupported: 'не поддерживается'};

function showError(message) { error.textContent = message; error.hidden = !message; }
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Не удалось выполнить запрос');
  return data;
}
function words(value, allowEmpty = false) {
  const items = value.split(',').map(word => word.trim());
  if (!value.trim()) return [];
  return items.filter(word => word || allowEmpty).map(word => word === '∅' ? '' : word);
}
function selectedAlgorithmIds() { return [...algorithmOptions.querySelectorAll('input:checked')].map(input => input.value); }
function updateAlgorithmCounter() { algorithmCounter.textContent = `${selectedAlgorithmIds().length} / 3`; }
function blockFor(index) { return catalog.find(block => block.index === index); }

function renderAlgorithmPicker() {
  algorithmOptions.replaceChildren();
  algorithms.forEach((algorithm, index) => {
    const label = document.createElement('label'); label.className = 'algorithm-option';
    const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.value = algorithm.id; checkbox.checked = index === 0;
    const copy = document.createElement('span'); const name = document.createElement('strong'); name.textContent = algorithm.name; const description = document.createElement('small'); description.textContent = algorithm.description; copy.append(name, description);
    checkbox.addEventListener('change', () => {
      if (selectedAlgorithmIds().length > 3) { checkbox.checked = false; showError('Можно сравнивать не больше трёх алгоритмов'); }
      else { showError(''); refreshSearch(); }
      updateAlgorithmCounter();
    });
    label.append(checkbox, copy); algorithmOptions.append(label);
  });
  updateAlgorithmCounter();
}

function createScore(result) {
  const metric = document.createElement('div'); metric.className = 'result-score';
  const bar = document.createElement('div'); bar.className = 'bar'; const fill = document.createElement('span'); fill.style.width = `${result.score * 100}%`; bar.append(fill);
  const text = document.createElement('strong'); text.textContent = `${Number((result.score * 100).toFixed(1))}%`;
  metric.append(bar, text); return metric;
}
function renderSearch(algorithmResponses) {
  algorithmResults.replaceChildren(); resultCount.textContent = String(algorithmResponses.length).padStart(2, '0');
  if (!algorithmResponses.length) { const empty = document.createElement('p'); empty.className = 'search-empty'; empty.textContent = 'Выберите алгоритм и введите запрос, чтобы увидеть ранжирование.'; algorithmResults.append(empty); return; }
  algorithmResponses.forEach(algorithm => {
    const panel = document.createElement('section'); panel.className = 'result-panel';
    const header = document.createElement('header'); const title = document.createElement('h3'); title.textContent = algorithm.name; const description = document.createElement('p'); description.textContent = algorithm.description; header.append(title, description); panel.append(header);
    const decision = algorithm.results[0]?.decision; if (decision) { const badge = document.createElement('span'); badge.className = `decision decision-${decision}`; badge.textContent = DECISIONS[decision]; title.append(badge); }
    const list = document.createElement('ol'); list.className = 'result-list';
    if (!algorithm.results.length) { const empty = document.createElement('li'); empty.className = 'result-none'; empty.textContent = 'Кандидатов нет: в запросе не найдено знакомых команд.'; list.append(empty); }
    algorithm.results.forEach((result, position) => {
      const block = blockFor(result.index); const item = document.createElement('li');
      const number = document.createElement('span'); number.className = 'result-index'; number.textContent = String(position + 1).padStart(2, '0');
      const copy = document.createElement('div'); copy.className = 'result-copy'; const played = document.createElement('strong'); played.textContent = result.text; const canonical = document.createElement('span'); canonical.textContent = block && block.text !== result.text ? `блок: ${block.text}` : 'каноническая форма'; copy.append(played, canonical);
      if (result.status || result.command) { const meta = document.createElement('div'); meta.className = 'result-meta'; if (result.command) { const command = document.createElement('span'); command.className = 'command-chip'; command.textContent = `КОМАНДА ${result.command}`; meta.append(command); } if (result.status) { const status = document.createElement('span'); status.className = `status-chip status-${result.status}`; status.textContent = STATUSES[result.status] || result.status; meta.append(status); } copy.append(meta); }
      (result.explain || []).forEach(line => { const explain = document.createElement('small'); explain.className = 'result-explain'; explain.textContent = line; copy.append(explain); });
      item.append(number, copy, createScore(result)); list.append(item);
    });
    panel.append(list); algorithmResults.append(panel);
  });
}
async function refreshSearch() {
  const current = ++searchSequence; const algorithmsToRun = selectedAlgorithmIds();
  if (!query.value.trim() || !algorithmsToRun.length) return renderSearch([]);
  try {
    const data = await request('/api/search', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({query: query.value, algorithms: algorithmsToRun})});
    if (current === searchSequence) { showError(''); renderSearch(data.algorithms); }
  } catch (errorResponse) { if (current === searchSequence) showError(errorResponse.message); }
}

function chips(kind, items) {
  if (!items?.length) return null;
  const group = document.createElement('div'); group.className = 'chip-group'; const title = document.createElement('span'); title.className = 'chip-label'; title.textContent = kind; group.append(title);
  items.forEach(item => { const chip = document.createElement('span'); chip.className = `chip ${kind === 'ДЕЙСТВИЯ' ? 'action-chip' : 'object-chip'}${item ? '' : ' empty-action'}`; chip.textContent = item || '∅'; chip.title = item ? '' : 'Форма без действия'; group.append(chip); }); return group;
}
function field(label, name, value, placeholder) {
  const wrapper = document.createElement('label'); wrapper.className = 'edit-field'; wrapper.textContent = label;
  const input = document.createElement('input'); input.name = name; input.maxLength = name === 'text' ? 200 : 800; input.required = name === 'text'; input.value = value || ''; input.placeholder = placeholder; wrapper.append(input); return wrapper;
}
function valuesFromForm(form) { return {text: form.querySelector('[name=text]').value, actions: words(form.querySelector('[name=actions]').value, true), objects: words(form.querySelector('[name=objects]').value)}; }
function createEditor(block, close) {
  const form = document.createElement('form'); form.className = 'inline-editor'; const grid = document.createElement('div'); grid.className = 'form-grid';
  grid.append(field('ТЕКСТ КОМАНДЫ', 'text', block.text, 'Например, включи свет на кухне'), field('СИНОНИМЫ ДЕЙСТВИЯ · через запятую', 'actions', block.actions?.map(action => action || '∅').join(', '), 'включить, зажечь, ∅'), field('ВАРИАНТЫ ОБЪЕКТА · через запятую', 'objects', block.objects?.join(', '), 'свет на кухне, кухонный свет'));
  const buttons = document.createElement('div'); buttons.className = 'form-buttons'; const save = document.createElement('button'); save.type = 'submit'; save.textContent = 'Сохранить'; const cancel = document.createElement('button'); cancel.type = 'button'; cancel.className = 'cancel'; cancel.textContent = 'Отмена'; cancel.addEventListener('click', close); buttons.append(save, cancel); form.append(grid, buttons);
  form.addEventListener('submit', async event => { event.preventDefault(); try { await request(`/api/commands/${block.id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(valuesFromForm(form))}); close(); await loadCatalog(); await refreshSearch(); } catch (errorResponse) { showError(errorResponse.message); } }); return form;
}
function renderLibrary() {
  libraryCount.textContent = String(catalog.length).padStart(2, '0'); libraryList.replaceChildren();
  if (!catalog.length) { const empty = document.createElement('p'); empty.className = 'empty'; empty.textContent = 'Список пока пуст. Добавьте блок или загрузите пример.'; libraryList.append(empty); return; }
  catalog.forEach(block => {
    const card = document.createElement('article'); card.className = 'library-card'; const title = document.createElement('strong'); title.textContent = block.text; card.append(title);
    const meta = document.createElement('div'); meta.className = 'command-meta'; const actionChips = chips('ДЕЙСТВИЯ', block.actions); const objectChips = chips('ОБЪЕКТЫ', block.objects); if (actionChips) meta.append(actionChips); if (objectChips) meta.append(objectChips); if (!meta.children.length) { const special = document.createElement('span'); special.className = 'special'; special.textContent = 'СПЕЦИАЛЬНАЯ КОМАНДА'; meta.append(special); } card.append(meta);
    const controls = document.createElement('div'); controls.className = 'row-controls'; const edit = document.createElement('button'); edit.className = 'edit'; edit.type = 'button'; edit.textContent = 'Изменить'; const remove = document.createElement('button'); remove.className = 'delete'; remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', `Удалить «${block.text}»`);
    let editor; edit.addEventListener('click', () => { if (editor) { editor.remove(); editor = null; edit.textContent = 'Изменить'; } else { editor = createEditor(block, () => { editor.remove(); editor = null; edit.textContent = 'Изменить'; }); card.append(editor); edit.textContent = 'Свернуть'; editor.querySelector('[name=text]').focus(); } });
    remove.addEventListener('click', async () => { if (!confirm(`Удалить блок «${block.text}»?`)) return; try { await request(`/api/commands/${block.id}`, {method: 'DELETE'}); await loadCatalog(); await refreshSearch(); } catch (errorResponse) { showError(errorResponse.message); } }); controls.append(edit, remove); card.append(controls); libraryList.append(card);
  });
}
async function loadCatalog() { const data = await request('/api/commands'); catalog = data.commands; renderLibrary(); }
async function initialise() {
  try { const [catalogResponse, algorithmsResponse] = await Promise.all([request('/api/commands'), request('/api/algorithms')]); catalog = catalogResponse.commands; algorithms = algorithmsResponse.algorithms; renderLibrary(); renderAlgorithmPicker(); renderSearch([]); }
  catch (errorResponse) { showError('Не удалось загрузить платформу: ' + errorResponse.message); }
}

query.addEventListener('input', refreshSearch);
document.querySelector('#toggle-add').addEventListener('click', () => { addForm.hidden = !addForm.hidden; if (!addForm.hidden) document.querySelector('#new-command').focus(); });
document.querySelector('#cancel-add').addEventListener('click', () => { addForm.hidden = true; showError(''); });
addForm.addEventListener('submit', async event => { event.preventDefault(); try { await request('/api/commands', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: document.querySelector('#new-command').value, actions: words(document.querySelector('#new-actions').value, true), objects: words(document.querySelector('#new-objects').value)})}); addForm.reset(); addForm.hidden = true; await loadCatalog(); await refreshSearch(); } catch (errorResponse) { showError(errorResponse.message); } });
document.querySelector('#examples').addEventListener('click', async () => { if (catalog.length && !confirm('Заменить текущий список готовым набором смысловых блоков?')) return; try { await request('/api/commands/examples', {method: 'POST'}); await loadCatalog(); await refreshSearch(); } catch (errorResponse) { showError(errorResponse.message); } });
document.querySelector('#clear').addEventListener('click', async () => { if (!catalog.length || !confirm('Удалить все смысловые блоки?')) return; try { await request('/api/commands', {method: 'DELETE'}); await loadCatalog(); await refreshSearch(); } catch (errorResponse) { showError(errorResponse.message); } });
initialise();
