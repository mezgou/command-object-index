const query = document.querySelector('#query');
const results = document.querySelector('#results');
const count = document.querySelector('#count');
const error = document.querySelector('#error');
const addForm = document.querySelector('#add-form');
const newCommand = document.querySelector('#new-command');
let sequence = 0;

function showError(message) { error.textContent = message; error.hidden = !message; }
async function request(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Не удалось выполнить запрос');
  return data;
}
function render(commands, searching) {
  count.textContent = String(commands.length).padStart(2, '0');
  results.replaceChildren();
  if (!commands.length) {
    const empty = document.createElement('div'); empty.className = 'empty';
    empty.textContent = 'Список пока пуст. Добавьте команду или загрузите пример.';
    results.append(empty); return;
  }
  commands.forEach((command, index) => {
    const row = document.createElement('div'); row.className = 'row';
    if (searching && command.similarity >= 80) row.classList.add('match');
    const label = document.createElement('div'); label.className = 'command';
    const number = document.createElement('span'); number.className = 'index'; number.textContent = String(index + 1).padStart(2, '0');
    const text = document.createElement('span'); text.className = 'command-text'; text.textContent = command.text;
    label.append(number, text);
    const metric = document.createElement('div'); metric.className = 'metric';
    const bar = document.createElement('div'); bar.className = 'bar';
    const fill = document.createElement('span'); fill.style.width = searching ? `${command.similarity}%` : '0%'; bar.append(fill);
    const details = document.createElement('span'); details.className = 'metric-details';
    const score = document.createElement('span'); score.className = 'score';
    score.textContent = searching ? `${Number(command.similarity.toFixed(1))}%` : '—';
    const distance = document.createElement('span'); distance.className = 'distance';
    distance.textContent = searching ? `${command.distance} прав.` : '';
    metric.title = searching ? `Расстояние: ${command.distance}; близость: ${Number(command.similarity.toFixed(1))}%` : 'Введите запрос для сравнения';
    details.append(score, distance); metric.append(bar, details);
    const remove = document.createElement('button'); remove.className = 'delete'; remove.type = 'button'; remove.textContent = '×'; remove.setAttribute('aria-label', `Удалить команду «${command.text}»`);
    remove.addEventListener('click', async () => { try { await request(`/api/commands/${command.id}`, {method:'DELETE'}); await refresh(); } catch (e) { showError(e.message); } });
    row.append(label, metric, remove); results.append(row);
  });
}
async function refresh() {
  const current = ++sequence; const value = query.value;
  try { const data = await request(`/api/commands?q=${encodeURIComponent(value)}`); if (current === sequence) { showError(''); render(data.commands, Boolean(value.trim())); } }
  catch (e) { if (current === sequence) showError('Не удалось загрузить команды. Проверьте подключение к серверу.'); }
}
query.addEventListener('input', refresh);
document.querySelector('#toggle-add').addEventListener('click', () => { addForm.hidden = !addForm.hidden; if (!addForm.hidden) newCommand.focus(); });
document.querySelector('#cancel-add').addEventListener('click', () => { addForm.hidden = true; showError(''); });
addForm.addEventListener('submit', async event => {
  event.preventDefault();
  try { await request('/api/commands', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:newCommand.value})}); newCommand.value = ''; addForm.hidden = true; await refresh(); }
  catch (e) { showError(e.message); }
});
document.querySelector('#examples').addEventListener('click', async () => {
  if (Number(count.textContent) && !confirm('Заменить текущий список готовым набором команд?')) return;
  try { await request('/api/commands/examples', {method:'POST'}); await refresh(); } catch (e) { showError(e.message); }
});
document.querySelector('#clear').addEventListener('click', async () => {
  if (!Number(count.textContent) || !confirm('Удалить все команды из списка?')) return;
  try { await request('/api/commands', {method:'DELETE'}); await refresh(); } catch (e) { showError(e.message); }
});
refresh();
