// 两个标签页只共享显示工具，不共享查询对象、条件或结果状态。
const element = id => document.getElementById(id);
const format = value => Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
const selectedPeople = new Map();
const toolTrace = [];
let agentBusy = false;
const labels = {
  'Sales.hospital_name': '医院', 'Sales.product_name': '产品',
  'Sales.province_name': '省份', 'Sales.total_amount': '销售额', 'Sales.total_quantity': '销量',
};

// 代码键保留在执行详情，业务表优先展示医院、产品名称。
function renderTable(id, rows) {
  const table = element(id);
  const columns = rows.length ? Object.keys(rows[0]).filter(member => member in labels) : ['Sales.total_amount'];
  const header = document.createElement('tr');
  for (const column of columns) {
    const cell = document.createElement('th');
    cell.textContent = labels[column];
    if (column.includes('total_')) cell.className = 'number';
    header.append(cell);
  }
  table.tHead.replaceChildren(header);
  table.tBodies[0].replaceChildren(...rows.map(row => {
    const line = document.createElement('tr');
    for (const column of columns) {
      const cell = document.createElement('td');
      cell.textContent = column.includes('total_') ? format(row[column]) : row[column];
      if (column.includes('total_')) cell.className = 'number';
      line.append(cell);
    }
    return line;
  }));
}

function optionLabel(id) {
  return element(id).selectedOptions[0].textContent;
}

function monthsFor(id) {
  return element(id).value === 'all' ? ['2026-01', '2026-02'] : [element(id).value];
}

// 标签支持左右键切换，两个区域保留各自条件，不发出额外查询。
function activateTab(name, focus = false) {
  for (const tabName of ['filter', 'agent']) {
    const active = name === tabName;
    const tab = element(tabName + '-tab');
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
    element(tabName + '-panel').hidden = !active;
  }
  if (focus) element(name + '-tab').focus();
}

for (const name of ['filter', 'agent']) {
  element(name + '-tab').addEventListener('click', () => activateTab(name));
  element(name + '-tab').addEventListener('keydown', event => {
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      activateTab(event.key === 'Home' ? 'filter' : event.key === 'End' ? 'agent' : name === 'filter' ? 'agent' : 'filter', true);
    }
  });
}

// 筛选方式调用诊断接口，数据正确性、预聚合和 SQL 证据都折叠在详情中。
async function queryFilters(event) {
  if (event) event.preventDefault();
  const controls = [...element('filter-form').querySelectorAll('select, button')];
  controls.forEach(control => { control.disabled = true; });
  element('filter-result').hidden = true;
  element('filter-error').textContent = '';
  element('filter-status').textContent = '正在查询销售数据…';
  const parameters = new URLSearchParams({
    employee: element('filter-person').value, month: element('filter-month').value,
    view: element('filter-group').value,
    mode: element('filter-mode').value,
  });
  if (element('filter-hospital').value) parameters.set('hospitals', element('filter-hospital').value);
  if (element('filter-product').value) parameters.set('products', element('filter-product').value);
  if (element('filter-mode').value === 'as_of') parameters.set('snapshot', element('filter-snapshot').value);
  try {
    const response = await fetch('/api/example?' + parameters, { headers: { 'X-Demo-Viewer': element('filter-viewer').value } });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error);
    element('filter-total').textContent = format(result.total);
    element('filter-summary').textContent = [optionLabel('filter-person'), optionLabel('filter-month'), optionLabel('filter-hospital'), optionLabel('filter-product')].join(' · ');
    renderTable('filter-table', result.data);
    element('filter-proof').textContent = '原始事实对账：' + format(result.rawTotal) + (result.total === result.rawTotal ? '，与查询结果一致。' : '，与结果不一致。') + (result.verifiedRollups.length ? '本次命中预聚合。' : '本次查询原始事实。');
    element('filter-architecture').textContent = '销售月 → 采用的组织快照：' + Object.entries(result.snapshots).map(([month, snapshot]) => month + ' → ' + snapshot).join('；');
    element('filter-query').textContent = JSON.stringify({ query: result.query, enforcedFilters: result.enforcedFilters }, null, 2);
    element('filter-sql').textContent = JSON.stringify({ rollups: result.verifiedRollups, physicalTables: result.physicalRollupTables, sql: result.cubeSql }, null, 2);
    element('filter-raw').textContent = result.rawSql + '\n参数：' + JSON.stringify(result.rawParameters);
    element('filter-result').hidden = false;
    element('filter-status').textContent = '';
  } catch (error) {
    element('filter-status').textContent = '';
    element('filter-error').textContent = error.message;
  } finally {
    controls.forEach(control => { control.disabled = false; });
  }
}

element('filter-form').addEventListener('submit', queryFilters);
element('filter-form').addEventListener('change', () => {
  element('filter-snapshot-field').hidden = element('filter-mode').value !== 'as_of';
  element('filter-result').hidden = true;
  element('filter-error').textContent = '';
  element('filter-status').textContent = '条件已修改，点击“查询销售额”查看结果。';
});

// 工具页使用普通业务工具，不执行筛选页的原始对账和诊断查询。
async function callTool(name, argumentsValue) {
  const response = await fetch('/api/tools/' + name, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Demo-Viewer': element('agent-viewer').value },
    body: JSON.stringify(argumentsValue),
  });
  const result = await response.json();
  toolTrace.push({ tool: name, arguments: argumentsValue, result });
  element('agent-trace').textContent = JSON.stringify(toolTrace.slice(-5), null, 2);
  if (!response.ok) throw new Error(result.error);
  return result;
}

// 逐期查询绑定销售月份；后端用与销售相同的规则选有效组织版本。
async function directoryResults(tool, args) {
  const mode = element('agent-mode').value;
  if (mode === 'period') {
    const results = [];
    for (const month of monthsFor('agent-month')) {
      const result = await callTool(tool, { ...args, sales_month: month });
      results.push({ month, result });
    }
    return results;
  }
  const params = mode === 'as_of' ? { ...args, snapshot: element('agent-snapshot').value } : args;
  return [{ result: await callTool(tool, params) }];
}

// 请求期间冻结本页条件，防止另一身份/月份的旧响应覆盖当前结果。
async function agentTask(action) {
  if (agentBusy) return;
  agentBusy = true;
  element('agent-error').textContent = '';
  element('agent-status').textContent = '正在调用工具…';
  element('agent-panel').querySelectorAll('button, input, select').forEach(control => { control.disabled = true; });
  try {
    await action();
  } catch (error) {
    element('agent-error').textContent = error.message;
  } finally {
    agentBusy = false;
    element('agent-status').textContent = '';
    element('agent-panel').querySelectorAll('button, input, select').forEach(control => { control.disabled = false; });
    renderSelection();
  }
}

function renderSelection() {
  const people = [...selectedPeople.values()];
  element('selected-people').replaceChildren();
  if (!people.length) {
    const text = document.createElement('p');
    text.className = 'hint';
    text.textContent = '尚未选择人员。';
    element('selected-people').append(text);
  }
  for (const person of people) {
    const button = document.createElement('button');
    button.className = 'person-chip';
    button.textContent = person.person_name + ' · ' + person.person_id + ' ×';
    button.setAttribute('aria-label', '移除 ' + person.person_name + ' ' + person.person_id);
    button.addEventListener('click', () => {
      selectedPeople.delete(person.person_id);
      element('agent-result').hidden = true;
      element('manager-results').replaceChildren();
      renderSelection();
    });
    element('selected-people').append(button);
  }
  element('agent-sales').disabled = agentBusy || !people.length;
  element('agent-managers').disabled = agentBusy || !people.length;
  element('selection-note').textContent = people.length > 1 ? '已选 ' + people.length + ' 人。业绩取医院产品的去重范围，不直接相加个人销售额。' : '';
}

// 每个候选显示具体辖区和工号，重名时由用户选择，不自动猜测。
function personRow(person, replace = false, month = null) {
  const row = document.createElement('div');
  row.className = 'person-row';
  const description = document.createElement('div');
  const title = document.createElement('p');
  title.textContent = person.person_name;
  const detail = document.createElement('small');
  detail.textContent = [month, person.assignments?.map(assignment => assignment.territory_name).join(' / '), '工号 ' + person.person_id].filter(Boolean).join(' · ');
  description.append(title, detail);
  const button = document.createElement('button');
  button.textContent = replace ? '改为查询这位领导' : '选择此人';
  button.setAttribute('aria-label', (replace ? '选择领导 ' : '选择 ') + person.person_name + ' ' + person.person_id);
  button.addEventListener('click', () => {
    if (replace) {
      selectedPeople.clear();
      // 领导是所标月份的任职人，选择后同步查询期间。
      if (month) element('agent-month').value = month;
    }
    selectedPeople.set(person.person_id, person);
    element('agent-result').hidden = true;
    element('manager-results').replaceChildren();
    renderSelection();
  });
  row.append(description, button);
  return row;
}

element('people-form').addEventListener('submit', event => {
  event.preventDefault();
  agentTask(async () => {
    element('people-candidates').replaceChildren();
    const results = await directoryResults('search_people', { name: element('people-name').value });
    const candidates = results.flatMap(({ month, result }) => result.people.map(person => personRow(person, false, month)));
    element('people-status').textContent = results.map(({ month, result }) =>
      (month ? month + ' · ' : '') + '架构 ' + result.snapshot + '：找到 ' + result.people.length + ' 人'
    ).join('；');
    element('people-candidates').replaceChildren(...candidates);
  });
});

element('agent-sales').addEventListener('click', () => agentTask(async () => {
  element('agent-result').hidden = true;
  const result = await callTool('query_sales', {
    person_ids: [...selectedPeople.keys()], months: monthsFor('agent-month'),
    architecture_mode: element('agent-mode').value,
    ...(element('agent-mode').value === 'as_of' ? { snapshot: element('agent-snapshot').value } : {}),
    group_by: 'detail',
  });
  element('agent-total').textContent = format(result.total);
  element('agent-summary').textContent = [...selectedPeople.values()].map(person => person.person_name).join('、') + ' · ' + optionLabel('agent-month') + ' · ' + optionLabel('agent-mode');
  renderTable('agent-table', result.data);
  element('agent-result').hidden = false;
}));

element('agent-managers').addEventListener('click', () => agentTask(async () => {
  const results = await directoryResults('get_managers', { person_ids: [...selectedPeople.keys()] });
  const managers = results.flatMap(({ month, result }) => result.managers.map(person => personRow(person, true, month)));
  element('manager-results').replaceChildren();
  const message = document.createElement('p');
  message.textContent = managers.length ? '已找到直属领导。选择后，可查询其完整团队业绩。' : '此架构下没有直属领导分配。';
  element('manager-results').append(message, ...managers);
}));

// 身份或组织变化时重新识别人，期间变化仅清除旧业绩；与筛选页完全独立。
for (const id of ['agent-viewer', 'agent-month', 'agent-mode', 'agent-snapshot']) {
  element(id).addEventListener('change', () => {
    element('agent-result').hidden = true;
    element('agent-error').textContent = '';
    element('agent-snapshot-field').hidden = element('agent-mode').value !== 'as_of';
    if (id !== 'agent-month' || element('agent-mode').value === 'period') {
      selectedPeople.clear();
      toolTrace.length = 0;
      element('people-candidates').replaceChildren();
      element('manager-results').replaceChildren();
      element('people-status').textContent = '登录人或组织口径已变化，请重新检索人员。';
      element('agent-trace').textContent = '等待新的工具调用。';
      renderSelection();
    }
  });
}

renderSelection();
queryFilters();
