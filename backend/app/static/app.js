let token = '';
let user = {};
let types = [];
let departments = [];
let selectedRequestId = null;

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch('/api' + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  });
  const data = await response.json();
  if (!response.ok) {
    let detail = data.detail;
    if (Array.isArray(detail)) detail = detail.map((item) => item.msg || item.message || JSON.stringify(item)).join('، ');
    else if (detail && typeof detail === 'object') detail = detail.message || detail.msg || JSON.stringify(detail);
    throw Error(detail || 'تعذر تنفيذ العملية');
  }
  return data;
}

async function loadDepartments() {
  departments = await api('/departments');
  updateSignupDepartmentField();
  updateAdminDepartmentField();
}

function updateSignupDepartmentField() {
  const isDepartmentManager = $('signupRole').value === 'DEPARTMENT_MANAGER';
  const availableDepartments = isDepartmentManager ? departments.filter((department) => !['فني مصنع', 'Drawing'].includes(department.name)) : departments;
  const select = $('signupDepartment');
  const selected = select.value;
  select.innerHTML = '<option value="">اختر القسم</option>' + availableDepartments.map((department) => `<option value="${department.id}">${escapeHtml(department.name)}</option>`).join('');
  if (availableDepartments.some((department) => String(department.id) === selected)) select.value = selected;
  $('signupDepartmentLabel').textContent = isDepartmentManager ? 'مسؤول عن أي قسم؟' : 'القسم (Department)';
  $('signupPendingMessage').classList.add('hidden');
}

function clearSignupDepartmentError() {
  $('signupDepartmentError').classList.add('hidden');
}

function updateAdminDepartmentField() {
  const roleCode = $('newRole').value;
  const isEmployee = roleCode === 'EMPLOYEE';
  const isDepartmentManager = roleCode === 'DEPARTMENT_MANAGER';
  const availableDepartments = isDepartmentManager ? departments.filter((department) => !['فني مصنع', 'Drawing'].includes(department.name)) : departments;
  const select = $('newDepartment');
  const selected = select.value;
  select.innerHTML = '<option value="">اختر القسم</option>' + availableDepartments.map((department) => `<option value="${department.id}">${escapeHtml(department.name)}</option>`).join('');
  if (availableDepartments.some((department) => String(department.id) === selected)) select.value = selected;
  $('newDepartmentField').classList.toggle('hidden', !isEmployee && !isDepartmentManager);
  $('newDepartmentLabel').textContent = isDepartmentManager ? 'مسؤول عن أي قسم؟' : 'القسم (Department)';
  select.required = isEmployee || isDepartmentManager;
}

async function login() {
  try {
    const data = await api('/auth/login', { method: 'POST', body: JSON.stringify({ email: $('email').value, password: $('password').value }) });
    await startSession(data);
  } catch (error) { alert(error.message); }
}

async function signup(event) {
  event.preventDefault();
  $('signupPendingMessage').classList.add('hidden');
  const departmentId = Number($('signupDepartment').value);
  if (!departmentId) {
    $('signupDepartmentError').classList.remove('hidden');
    $('signupDepartment').focus();
    return;
  }
  try {
    const roleCode = $('signupRole').value;
    const data = await api('/auth/signup', { method: 'POST', body: JSON.stringify({ full_name: $('signupName').value, email: $('signupEmail').value, password: $('signupPassword').value, department_id: departmentId, role_code: roleCode }) });
    if (data.status === 'PENDING_ACTIVATION') {
      $('signupPendingMessage').textContent = data.message;
      $('signupPendingMessage').classList.remove('hidden');
      return;
    }
    await startSession(data);
  } catch (error) { alert(error.message); }
}

async function startSession(data) {
  token = data.access_token;
  user = data.user;
  sessionStorage.setItem('tafaseelToken', token);
  $('accountName').textContent = user.name;
  $('accountName').classList.remove('hidden');
  $('loginLogo').classList.add('hidden');
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  $('logout').classList.remove('hidden');
  await init();
}

async function toggleSignup() {
  const form = $('signupForm');
  const opening = form.classList.contains('hidden');
  form.classList.toggle('hidden');
  if (!opening || departments.length) return;

  const select = $('signupDepartment');
  select.disabled = true;
  select.innerHTML = '<option value="">جاري تحميل الأقسام...</option>';
  try {
    await loadDepartments();
    $('signupDepartmentError').classList.add('hidden');
  } catch (error) {
    select.innerHTML = '<option value="">تعذر تحميل الأقسام</option>';
    $('signupDepartmentError').textContent = 'تعذر تحميل الأقسام. تحقق من اتصال الخادم ثم أغلق النموذج وافتحه للمحاولة مرة أخرى.';
    $('signupDepartmentError').classList.remove('hidden');
  } finally {
    select.disabled = false;
  }
}

async function init() {
  types = await api('/request-types');
  $('type').innerHTML = `<option value="">اختر نوع الطلب</option>${types.map((type) => `<option value="${type.code}">${type.name_ar}</option>`).join('')}`;
  $('newBtn').classList.toggle('hidden', !['EMPLOYEE', 'DEPARTMENT_MANAGER', 'HR', 'ADMIN'].includes(user.role));
  $('archiveBtn').classList.toggle('hidden', user.role !== 'HR');
  $('adminPanel').classList.toggle('hidden', user.role !== 'ADMIN');
  renderFields();
  await Promise.all([dashboard(), loadRequests(), loadNotifications(), user.role === 'ADMIN' ? loadAdminUsers() : Promise.resolve()]);
}

async function dashboard() {
  const data = await api('/dashboard');
  const counts = data.counts;
  $('summary').innerHTML = [
    ['إجمالي الطلبات', data.total],
    ['بانتظار الموافقة', (counts.PENDING_EXECUTIVE || 0) + (counts.PENDING_DEPARTMENT_MANAGER || 0) + (counts.PENDING_DRAWING || 0) + (counts.PENDING_HR || 0)],
    ['موافق عليه', counts.APPROVED || 0],
    ['إشعارات جديدة', data.unread_notifications]
  ].map(([label, value]) => `<div class="bg-white shadow rounded-xl p-4"><p class="text-slate-500 text-sm">${label}</p><strong class="text-2xl">${value}</strong></div>`).join('');
}

function showNew() { $('form').classList.toggle('hidden'); }

function renderFields() {
  const type = types.find((item) => item.code === $('type').value);
  if (!type) {
    $('fields').innerHTML = '<p class="text-slate-500 md:col-span-2">اختر نوع الطلب لعرض الحقول المطلوبة.</p>';
    return;
  }
  $('fields').innerHTML = type.fields.map((field) => {
    const label = `<label class="block text-sm">${field.label}${field.required ? ' *' : ''}`;
    if (field.type === 'textarea') return `${label}<textarea data-key="${field.key}" class="border rounded p-2 mt-1 w-full"></textarea></label>`;
    if (field.type === 'select') return `${label}<select data-key="${field.key}" class="border rounded p-2 mt-1 w-full"><option value=""></option>${field.options.map((option) => `<option>${option}</option>`).join('')}</select></label>`;
    return `${label}<input data-key="${field.key}" type="${field.type === 'calculated' ? 'number' : field.type}" ${field.type === 'calculated' ? 'readonly' : ''} class="border rounded p-2 mt-1 w-full"></label>`;
  }).join('');
  document.querySelectorAll('[data-key="meter_reading"],[data-key="price_per_km"]').forEach((element) => {
    element.oninput = () => {
      const meter = document.querySelector('[data-key="meter_reading"]')?.value || 0;
      const price = document.querySelector('[data-key="price_per_km"]')?.value || 0;
      const value = document.querySelector('[data-key="value"]');
      if (value) value.value = meter * price;
    };
  });
}

async function submitRequest() {
  try {
    const formData = {};
    document.querySelectorAll('[data-key]').forEach((element) => { formData[element.dataset.key] = element.value; });
    await api('/requests', { method: 'POST', body: JSON.stringify({ request_type_code: $('type').value, form_data: formData }) });
    $('form').classList.add('hidden');
    await Promise.all([dashboard(), loadRequests()]);
  } catch (error) { alert(error.message); }
}

async function loadRequests() {
  const rows = await api('/requests');
  const incoming = ['EMPLOYEE', 'DEPARTMENT_MANAGER'].includes(user.role)
    ? rows.filter((request) => request.requester.id !== user.id)
    : [];
  const personal = ['EMPLOYEE', 'DEPARTMENT_MANAGER'].includes(user.role)
    ? rows.filter((request) => request.requester.id === user.id)
    : rows;
  const inboxTitle = user.role === 'DEPARTMENT_MANAGER' && user.department === 'الانتاج'
    ? 'طلبات القسم وموظفي Drawing الواردة للمراجعة'
    : user.role === 'DEPARTMENT_MANAGER'
      ? 'طلبات القسم الواردة للمراجعة'
      : 'طلبات فني المصنع الواردة إلى Drawing';
  $('technicianInboxTitle').textContent = inboxTitle;
  $('technicianInbox').classList.toggle('hidden', incoming.length === 0);
  $('technicianRequests').innerHTML = renderRequestRows(incoming, 'لا توجد طلبات واردة حالياً.', true);
  $('requests').innerHTML = renderRequestRows(personal, 'لا توجد طلبات حالياً.');
}

async function toggleArchive() {
  const section = $('archiveSection');
  const opening = section.classList.contains('hidden');
  section.classList.toggle('hidden');
  if (opening) await loadArchive();
}

async function loadArchive() {
  try {
    const rows = await api('/hr/archive');
    $('archiveRequests').innerHTML = rows.length
      ? rows.map((request) => `<tr class="border-t"><td class="p-3 whitespace-nowrap">${escapeHtml(formatDate(request.created_at))}</td><td class="p-3">#${request.id}</td><td class="p-3">${escapeHtml(request.request_type.name_ar)}</td><td class="p-3">${escapeHtml(request.requester.full_name)}</td><td class="p-3"><span class="px-2 py-1 rounded bg-slate-100">${escapeHtml(request.status_label)}</span></td><td class="p-3"><button onclick="details(${request.id})" class="text-sky-700 underline">عرض التفاصيل</button></td></tr>`).join('')
      : '<tr><td class="p-5 text-center text-slate-500" colspan="6">لا توجد طلبات موافق عليها من الموظفين أو مسؤولي الأقسام حالياً.</td></tr>';
  } catch (error) {
    alert(error.message);
  }
}

function renderRequestRows(rows, emptyMessage, readOnly = false) {
  return rows.length
    ? rows.map((request) => `<tr class="border-t"><td class="p-3">#${request.id}</td><td class="p-3">${escapeHtml(request.request_type.name_ar)}</td><td class="p-3">${escapeHtml(request.requester.full_name)}</td><td class="p-3"><span class="px-2 py-1 rounded bg-slate-100">${escapeHtml(request.status_label)}</span></td><td class="p-3"><button onclick="details(${request.id})" class="text-sky-700 underline">${readOnly ? 'المراجعة والقرار' : 'التفاصيل والمتابعة'}</button></td></tr>`).join('')
    : `<tr><td class="p-5 text-center text-slate-500" colspan="5">${emptyMessage}</td></tr>`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[character]);
}

function displayValue(value) {
  if (value === null || value === undefined || value === '') return 'غير محدد';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString('ar') : 'غير محدد';
}

function actionLabel(action) {
  if (action === 'REQUEST_SUBMITTED') return 'تم تقديم الطلب';
  if (action.endsWith('_APPROVED')) return 'تمت الموافقة';
  if (action.endsWith('_REJECTED')) return 'تم رفض الطلب';
  return action;
}

async function details(id) {
  try {
    const request = await api(`/requests/${id}`);
    selectedRequestId = id;
    $('detailTitle').textContent = `${request.request_type.name_ar} #${request.id}`;
    $('detailStatus').textContent = `${request.status_label}${request.current_role ? ` · بانتظار: ${roleLabel(request.current_role)}` : ''}`;
    $('detailRequester').textContent = `مقدم الطلب: ${request.requester.full_name} · الرقم الوظيفي: ${request.requester.employee_id} · تاريخ التقديم: ${formatDate(request.created_at)}`;
    const type = types.find((item) => item.code === request.request_type.code);
    const fieldLabels = new Map((type?.fields || []).map((field) => [field.key, field.label]));
    $('detailFields').innerHTML = Object.entries(request.form_data || {}).map(([key, value]) => `<div class="rounded border p-3"><dt class="text-sm text-slate-500">${escapeHtml(fieldLabels.get(key) || key)}</dt><dd class="mt-1 whitespace-pre-wrap break-words">${escapeHtml(displayValue(value))}</dd></div>`).join('') || '<p class="text-slate-500">لا توجد تفاصيل مضافة.</p>';
    $('detailHistory').innerHTML = request.history.length
      ? request.history.map((item) => `<li class="border-r-2 border-sky-700 pr-3"><p class="font-medium">${escapeHtml(actionLabel(item.action))} · ${escapeHtml(item.actor || roleLabel(item.role) || '')}</p>${item.comment ? `<p class="mt-1 whitespace-pre-wrap text-slate-700">${escapeHtml(item.comment)}</p>` : ''}<time class="text-xs text-slate-500">${escapeHtml(new Date(item.at).toLocaleString('ar'))}</time></li>`).join('')
      : '<li class="text-slate-500">تم استلام الطلب، ولم تُسجل قرارات بعد.</li>';
    const pendingRole = ({ PENDING_EXECUTIVE: 'EXECUTIVE_MANAGER', PENDING_DEPARTMENT_MANAGER: 'DEPARTMENT_MANAGER', PENDING_DRAWING: 'DRAWING', PENDING_HR: 'HR' })[request.status];
    const drawingReviewer = pendingRole === 'DRAWING' && user.role === 'EMPLOYEE' && user.department === 'Drawing';
    const canDecide = Boolean(pendingRole) && (user.role === 'ADMIN' || user.role === pendingRole || drawingReviewer);
    $('decisionPanel').classList.toggle('hidden', !canDecide);
    $('decisionComment').value = '';
    $('requestDialog').showModal();
  } catch (error) { alert(error.message); }
}

function roleLabel(role) {
  return ({ EXECUTIVE_MANAGER: 'المدير التنفيذي', DEPARTMENT_MANAGER: 'مسؤول القسم', DRAWING: 'قسم Drawing', HR: 'الموارد البشرية' })[role] || role || '';
}

function closeDetails() {
  $('requestDialog').close();
  selectedRequestId = null;
}

async function submitDecision(action) {
  const comment = $('decisionComment').value.trim();
  if (action === 'REJECT' && !comment) {
    alert('يرجى كتابة سبب الرفض قبل تأكيده.');
    $('decisionComment').focus();
    return;
  }
  try {
    await api(`/requests/${selectedRequestId}/decision`, { method: 'POST', body: JSON.stringify({ action, comment: comment || null }) });
    closeDetails();
    await Promise.all([dashboard(), loadRequests(), loadNotifications()]);
  } catch (error) { alert(error.message); }
}

async function loadNotifications() {
  const notifications = await api('/notifications');
  $('notifications').innerHTML = notifications.length
    ? notifications.map((item) => `<li class="border-b pb-2"><button class="text-right text-sky-800 underline" onclick="details(${item.request_id})">${escapeHtml(item.message)}</button><time class="block text-xs text-slate-500 mt-1">${escapeHtml(new Date(item.created_at).toLocaleString('ar'))}</time></li>`).join('')
    : '<li class="text-slate-500">لا توجد إشعارات جديدة.</li>';
}

async function loadAdminUsers() {
  const users = await api('/admin/users');
  $('adminUsers').innerHTML = users.map((item) => {
    const pendingManager = item.role === 'DEPARTMENT_MANAGER' && item.registration_status === 'PENDING';
    const rejectedManager = item.role === 'DEPARTMENT_MANAGER' && item.registration_status === 'REJECTED';
    const status = pendingManager ? 'بانتظار الموافقة' : rejectedManager ? 'مرفوض' : item.active ? 'فعال' : 'معطل';
    const actions = pendingManager
      ? `<button onclick="decideManagerRegistration(${item.id}, 'APPROVE')" class="ml-2 text-emerald-700">موافقة</button><button onclick="decideManagerRegistration(${item.id}, 'REJECT')" class="text-red-700">رفض</button>`
      : rejectedManager ? '—' : `<button onclick="toggleUser(${item.id}, ${!item.active})" class="text-sky-700">${item.active ? 'تعطيل' : 'تفعيل'}</button>${item.active ? `<button onclick="resetUserPassword(${item.id}, '${escapeHtml(item.full_name)}')" class="mr-2 text-amber-700">إعادة تعيين كلمة المرور</button>` : ''}`;
    return `<tr class="border-t"><td class="p-2">${escapeHtml(item.full_name)}</td><td class="p-2">${escapeHtml(item.email)}</td><td class="p-2">${escapeHtml(item.department || '—')}</td><td class="p-2">${escapeHtml(item.role_name)}</td><td class="p-2">${status}</td><td class="p-2 whitespace-nowrap">${actions}</td></tr>`;
  }).join('');
}

async function createUser() {
  try {
    const roleCode = $('newRole').value;
    const departmentId = ['EMPLOYEE', 'DEPARTMENT_MANAGER'].includes(roleCode) ? Number($('newDepartment').value) : null;
    await api('/admin/users', { method: 'POST', body: JSON.stringify({ full_name: $('newName').value, employee_id: $('newEmployeeId').value, email: $('newEmail').value, password: $('newPassword').value, role_code: roleCode, department_id: departmentId }) });
    ['newName', 'newEmployeeId', 'newEmail', 'newPassword', 'newDepartment'].forEach((id) => { $(id).value = ''; });
    await loadAdminUsers();
  } catch (error) { alert(error.message); }
}

async function toggleUser(id, active) {
  try { await api(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify({ active }) }); await loadAdminUsers(); }
  catch (error) { alert(error.message); }
}

async function resetUserPassword(id, name) {
  if (!confirm(`سيتم تغيير كلمة مرور ${name} فوراً. هل تريد المتابعة؟`)) return;
  try {
    const result = await api(`/admin/users/${id}/reset-password`, { method: 'POST' });
    alert(`تم تغيير كلمة المرور.\n\nكلمة المرور الجديدة (تظهر مرة واحدة):\n${result.temporary_password}\n\nانسخها واحفظها وشاركها مع المستخدم عبر قناة آمنة.`);
  } catch (error) { alert(error.message); }
}

async function decideManagerRegistration(id, action) {
  try {
    await api(`/admin/users/${id}/registration-decision`, { method: 'POST', body: JSON.stringify({ action }) });
    await loadAdminUsers();
  } catch (error) { alert(error.message); }
}

loadDepartments().catch((error) => console.error('تعذر تحميل الأقسام', error));
$('logout').onclick = () => { sessionStorage.clear(); location.reload(); };
token = sessionStorage.getItem('tafaseelToken') || '';
if (token) {
  api('/dashboard').then(async () => {
    const response = await fetch('/api/auth/me', { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) throw Error('جلسة غير صالحة');
    const data = await response.json();
    user = data.user;
    $('accountName').textContent = user.name;
    $('accountName').classList.remove('hidden');
    $('loginLogo').classList.add('hidden');
    $('login').classList.add('hidden');
    $('app').classList.remove('hidden');
    $('logout').classList.remove('hidden');
    await init();
  }).catch(() => { sessionStorage.clear(); token = ''; });
}
