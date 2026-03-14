import os
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client
from typing import Optional

# ── Supabase client ───────────────────────────────────────────────────────────
def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

# ── Simple token auth ─────────────────────────────────────────────────────────
ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me-in-production")

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True

# ── Schemas ───────────────────────────────────────────────────────────────────
class ProductCreate(BaseModel):
    name: str
    description: str
    price: int          # in paise  (e.g. 19900 = ₹199)
    active: bool = True

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    active: Optional[bool] = None

# ── Router ────────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/admin", tags=["admin"])

# ── Admin UI ──────────────────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def admin_ui():
    return HTMLResponse(ADMIN_HTML)

# ── Products CRUD ─────────────────────────────────────────────────────────────
@router.get("/products", dependencies=[Depends(verify_admin)])
def list_products(supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").select("*").order("created_at", desc=True).execute()
    return {"products": result.data}

@router.post("/products", dependencies=[Depends(verify_admin)], status_code=201)
def create_product(body: ProductCreate, supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").insert({
        "name":        body.name,
        "description": body.description,
        "price":       body.price,
        "active":      body.active,
    }).execute()
    return {"product": result.data[0]}

@router.patch("/products/{product_id}", dependencies=[Depends(verify_admin)])
def update_product(product_id: str, body: ProductUpdate, supabase: Client = Depends(get_supabase)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = supabase.table("products").update(updates).eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": result.data[0]}

@router.delete("/products/{product_id}", dependencies=[Depends(verify_admin)])
def delete_product(product_id: str, supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").delete().eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": True, "id": product_id}

@router.get("/purchases", dependencies=[Depends(verify_admin)])
def list_purchases(supabase: Client = Depends(get_supabase)):
    result = supabase.table("purchases").select("*").order("created_at", desc=True).execute()
    return {"purchases": result.data}

# ── Embedded Admin HTML ───────────────────────────────────────────────────────
ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Admin Panel</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
  :root{
    --bg:#0a0a0f;--surface:#111118;--card:#16161f;--border:#1e1e2e;
    --accent:#f97316;--accent2:#fb923c;--text:#e8e8f0;--muted:#6b6b80;
    --green:#22c55e;--red:#ef4444;--blue:#3b82f6;
    --radius:10px;--font:'Syne',sans-serif;--mono:'DM Mono',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font);min-height:100vh}
  /* grid bg */
  body::before{content:'';position:fixed;inset:0;
    background-image:linear-gradient(var(--border) 1px,transparent 1px),
    linear-gradient(90deg,var(--border) 1px,transparent 1px);
    background-size:40px 40px;opacity:.35;pointer-events:none;z-index:0}
  .wrap{position:relative;z-index:1;max-width:960px;margin:0 auto;padding:32px 20px}

  /* header */
  header{display:flex;align-items:center;gap:16px;margin-bottom:40px;padding-bottom:24px;border-bottom:1px solid var(--border)}
  .logo{width:42px;height:42px;background:var(--accent);border-radius:8px;display:grid;place-items:center;font-size:20px;flex-shrink:0}
  h1{font-size:1.6rem;font-weight:800;letter-spacing:-.02em}
  h1 span{color:var(--accent)}
  .badge{margin-left:auto;background:#1a1a2e;border:1px solid var(--border);border-radius:20px;padding:4px 14px;font-size:.75rem;color:var(--muted);font-family:var(--mono)}

  /* auth gate */
  #auth-gate{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:32px;max-width:420px;margin:0 auto}
  #auth-gate h2{font-size:1.1rem;margin-bottom:20px;font-weight:700}
  #auth-gate p{font-size:.82rem;color:var(--muted);margin-bottom:20px}

  /* tabs */
  .tabs{display:flex;gap:4px;margin-bottom:28px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:4px}
  .tab{padding:8px 20px;border-radius:7px;cursor:pointer;font-size:.88rem;font-weight:600;color:var(--muted);transition:all .2s;border:none;background:none;font-family:var(--font)}
  .tab.active{background:var(--accent);color:#fff}
  .tab:hover:not(.active){color:var(--text)}

  /* form card */
  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:28px;margin-bottom:24px}
  .card-title{font-size:1rem;font-weight:700;margin-bottom:20px;display:flex;align-items:center;gap:8px}
  .card-title::before{content:'';width:4px;height:18px;background:var(--accent);border-radius:2px;display:block}
  .form-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .form-group{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}
  .form-group.full{grid-column:1/-1}
  label{font-size:.78rem;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
  input,textarea,select{background:#0d0d14;border:1px solid var(--border);border-radius:7px;color:var(--text);padding:10px 14px;font-family:var(--font);font-size:.9rem;outline:none;transition:border .2s;width:100%}
  input:focus,textarea:focus,select:focus{border-color:var(--accent)}
  textarea{resize:vertical;min-height:90px}
  .price-wrap{position:relative}
  .price-wrap span{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--muted);font-size:.9rem;pointer-events:none}
  .price-wrap input{padding-left:28px}
  .toggle-row{display:flex;align-items:center;gap:10px}
  .toggle{width:44px;height:24px;background:var(--border);border-radius:12px;cursor:pointer;position:relative;transition:background .2s;flex-shrink:0;border:none}
  .toggle.on{background:var(--green)}
  .toggle::after{content:'';position:absolute;width:18px;height:18px;background:#fff;border-radius:50%;top:3px;left:3px;transition:left .2s}
  .toggle.on::after{left:23px}
  .toggle-label{font-size:.85rem;color:var(--muted)}

  /* buttons */
  .btn{padding:10px 22px;border-radius:7px;font-family:var(--font);font-size:.88rem;font-weight:700;cursor:pointer;border:none;transition:all .2s;display:inline-flex;align-items:center;gap:6px}
  .btn-primary{background:var(--accent);color:#fff}
  .btn-primary:hover{background:var(--accent2);transform:translateY(-1px)}
  .btn-ghost{background:transparent;color:var(--muted);border:1px solid var(--border)}
  .btn-ghost:hover{color:var(--text);border-color:var(--muted)}
  .btn-danger{background:transparent;color:var(--red);border:1px solid #2a1010}
  .btn-danger:hover{background:#2a1010}
  .btn-sm{padding:6px 14px;font-size:.8rem}
  .btn-row{display:flex;gap:10px;align-items:center;margin-top:4px}

  /* product table */
  .table-wrap{overflow-x:auto}
  table{width:100%;border-collapse:collapse}
  th{text-align:left;font-size:.72rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding:8px 14px;border-bottom:1px solid var(--border)}
  td{padding:13px 14px;border-bottom:1px solid var(--border);font-size:.88rem;vertical-align:middle}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:rgba(249,115,22,.04)}
  .pill{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.72rem;font-weight:600}
  .pill-green{background:rgba(34,197,94,.15);color:var(--green)}
  .pill-red{background:rgba(239,68,68,.15);color:var(--red)}
  .mono{font-family:var(--mono);font-size:.82rem;color:var(--muted)}
  .price-cell{font-family:var(--mono);color:var(--accent);font-weight:500}

  /* empty */
  .empty{text-align:center;padding:48px 20px;color:var(--muted)}
  .empty-icon{font-size:2.5rem;margin-bottom:12px}

  /* toast */
  #toast{position:fixed;bottom:28px;right:28px;background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:12px 20px;font-size:.85rem;font-weight:600;transform:translateY(80px);opacity:0;transition:all .3s;z-index:999;min-width:220px}
  #toast.show{transform:translateY(0);opacity:1}
  #toast.ok{border-left:3px solid var(--green);color:var(--green)}
  #toast.err{border-left:3px solid var(--red);color:var(--red)}

  /* loader */
  .spin{width:16px;height:16px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;display:inline-block}
  @keyframes spin{to{transform:rotate(360deg)}}

  /* modal backdrop */
  .modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;align-items:center;justify-content:center}
  .modal.open{display:flex}
  .modal-box{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:28px;width:100%;max-width:480px;animation:slideUp .25s ease}
  @keyframes slideUp{from{transform:translateY(30px);opacity:0}to{transform:translateY(0);opacity:1}}
  .modal-title{font-size:1rem;font-weight:700;margin-bottom:20px}

  /* purchases */
  .status-paid{color:var(--green)}
  .status-pending{color:var(--accent)}
  .status-failed{color:var(--red)}

  @media(max-width:600px){.form-row{grid-template-columns:1fr}.btn-row{flex-wrap:wrap}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo">⚡</div>
    <div>
      <h1>Admin <span>Panel</span></h1>
      <div style="font-size:.78rem;color:var(--muted);margin-top:2px">Product & Order Management</div>
    </div>
    <div class="badge" id="env-badge">production</div>
  </header>

  <!-- AUTH GATE -->
  <div id="auth-gate">
    <h2>🔐 Admin Access</h2>
    <p>Enter your admin secret token to continue.</p>
    <div class="form-group">
      <label>Admin Token</label>
      <input type="password" id="token-input" placeholder="Enter ADMIN_SECRET…" autocomplete="off"/>
    </div>
    <button class="btn btn-primary" onclick="login()">Unlock Panel →</button>
  </div>

  <!-- MAIN PANEL (hidden until authed) -->
  <div id="main-panel" style="display:none">
    <div class="tabs">
      <button class="tab active" onclick="switchTab('products')">📦 Products</button>
      <button class="tab" onclick="switchTab('purchases')">💳 Purchases</button>
    </div>

    <!-- PRODUCTS TAB -->
    <div id="tab-products">
      <div class="card">
        <div class="card-title">Add New Product</div>
        <div class="form-row">
          <div class="form-group">
            <label>Product Name</label>
            <input id="p-name" type="text" placeholder="e.g. Premium Course"/>
          </div>
          <div class="form-group">
            <label>Price (₹)</label>
            <div class="price-wrap">
              <span>₹</span>
              <input id="p-price" type="number" placeholder="199" min="1"/>
            </div>
          </div>
          <div class="form-group full">
            <label>Description</label>
            <textarea id="p-desc" placeholder="What does this product include?"></textarea>
          </div>
          <div class="form-group">
            <label>Status</label>
            <div class="toggle-row">
              <button class="toggle on" id="p-active-toggle" onclick="toggleActive()"></button>
              <span class="toggle-label" id="p-active-label">Active</span>
            </div>
          </div>
        </div>
        <div class="btn-row">
          <button class="btn btn-primary" onclick="createProduct()">
            <span id="create-btn-text">+ Add Product</span>
          </button>
          <button class="btn btn-ghost" onclick="clearForm()">Clear</button>
        </div>
      </div>

      <div class="card">
        <div class="card-title">All Products</div>
        <div class="table-wrap">
          <table id="products-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Description</th>
                <th>Price</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody id="products-body">
              <tr><td colspan="5"><div class="empty"><div class="spin"></div></div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- PURCHASES TAB -->
    <div id="tab-purchases" style="display:none">
      <div class="card">
        <div class="card-title">All Purchases</div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Customer</th>
                <th>Email</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Order ID</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody id="purchases-body">
              <tr><td colspan="6"><div class="empty"><div class="spin"></div></div></td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Edit Modal -->
<div class="modal" id="edit-modal">
  <div class="modal-box">
    <div class="modal-title">✏️ Edit Product</div>
    <input type="hidden" id="edit-id"/>
    <div class="form-group">
      <label>Name</label>
      <input id="edit-name" type="text"/>
    </div>
    <div class="form-group">
      <label>Description</label>
      <textarea id="edit-desc"></textarea>
    </div>
    <div class="form-group">
      <label>Price (₹)</label>
      <div class="price-wrap"><span>₹</span><input id="edit-price" type="number" style="padding-left:28px"/></div>
    </div>
    <div class="form-group">
      <label>Status</label>
      <div class="toggle-row">
        <button class="toggle" id="edit-active-toggle" onclick="toggleEditActive()"></button>
        <span class="toggle-label" id="edit-active-label">Inactive</span>
      </div>
    </div>
    <div class="btn-row" style="margin-top:20px">
      <button class="btn btn-primary" onclick="saveEdit()">Save Changes</button>
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
let TOKEN = '';
let editActive = false;
let createActive = true;
const BASE = window.location.origin;

function login(){
  const t = document.getElementById('token-input').value.trim();
  if(!t){ toast('Enter a token','err'); return; }
  TOKEN = t;
  document.getElementById('auth-gate').style.display = 'none';
  document.getElementById('main-panel').style.display = 'block';
  loadProducts();
}
document.getElementById('token-input').addEventListener('keydown', e => e.key==='Enter' && login());

function switchTab(tab){
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById('tab-products').style.display = tab==='products'?'block':'none';
  document.getElementById('tab-purchases').style.display = tab==='purchases'?'block':'none';
  if(tab==='purchases') loadPurchases();
}

function toggleActive(){
  createActive = !createActive;
  const btn = document.getElementById('p-active-toggle');
  const lbl = document.getElementById('p-active-label');
  btn.classList.toggle('on', createActive);
  lbl.textContent = createActive ? 'Active' : 'Inactive';
}
function toggleEditActive(){
  editActive = !editActive;
  const btn = document.getElementById('edit-active-toggle');
  const lbl = document.getElementById('edit-active-label');
  btn.classList.toggle('on', editActive);
  lbl.textContent = editActive ? 'Active' : 'Inactive';
}

function clearForm(){
  ['p-name','p-price','p-desc'].forEach(id=>document.getElementById(id).value='');
  createActive = true;
  document.getElementById('p-active-toggle').classList.add('on');
  document.getElementById('p-active-label').textContent = 'Active';
}

async function api(method, path, body){
  const opts = { method, headers:{'Content-Type':'application/json','x-admin-token':TOKEN} };
  if(body) opts.body = JSON.stringify(body);
  const res = await fetch(BASE+path, opts);
  if(!res.ok){ const e=await res.json(); throw new Error(e.detail||'Error'); }
  return res.json();
}

async function loadProducts(){
  try{
    const data = await api('GET','/admin/products');
    renderProducts(data.products||[]);
  }catch(e){ toast(e.message,'err'); }
}

function renderProducts(products){
  const tbody = document.getElementById('products-body');
  if(!products.length){
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty"><div class="empty-icon">📦</div>No products yet</div></td></tr>`;
    return;
  }
  tbody.innerHTML = products.map(p=>`
    <tr>
      <td><strong>${esc(p.name)}</strong></td>
      <td style="max-width:220px;color:var(--muted);font-size:.82rem">${esc(p.description||'—').substring(0,80)}${p.description&&p.description.length>80?'…':''}</td>
      <td class="price-cell">₹${(p.price/100).toFixed(2)}</td>
      <td><span class="pill ${p.active?'pill-green':'pill-red'}">${p.active?'Active':'Inactive'}</span></td>
      <td>
        <div class="btn-row">
          <button class="btn btn-ghost btn-sm" onclick='openEdit(${JSON.stringify(p)})'>Edit</button>
          <button class="btn btn-danger btn-sm" onclick="deleteProduct('${p.id}')">Delete</button>
        </div>
      </td>
    </tr>`).join('');
}

async function createProduct(){
  const name = document.getElementById('p-name').value.trim();
  const desc = document.getElementById('p-desc').value.trim();
  const priceRs = parseFloat(document.getElementById('p-price').value);
  if(!name||!desc||isNaN(priceRs)||priceRs<=0){ toast('Fill in all fields','err'); return; }
  const btn = document.getElementById('create-btn-text');
  btn.innerHTML = '<span class="spin"></span> Adding…';
  try{
    await api('POST','/admin/products',{name,description:desc,price:Math.round(priceRs*100),active:createActive});
    toast('Product created ✓','ok');
    clearForm();
    loadProducts();
  }catch(e){ toast(e.message,'err'); }
  btn.textContent = '+ Add Product';
}

function openEdit(p){
  document.getElementById('edit-id').value = p.id;
  document.getElementById('edit-name').value = p.name;
  document.getElementById('edit-desc').value = p.description||'';
  document.getElementById('edit-price').value = (p.price/100).toFixed(2);
  editActive = p.active;
  document.getElementById('edit-active-toggle').classList.toggle('on', editActive);
  document.getElementById('edit-active-label').textContent = editActive?'Active':'Inactive';
  document.getElementById('edit-modal').classList.add('open');
}
function closeModal(){ document.getElementById('edit-modal').classList.remove('open'); }

async function saveEdit(){
  const id    = document.getElementById('edit-id').value;
  const name  = document.getElementById('edit-name').value.trim();
  const desc  = document.getElementById('edit-desc').value.trim();
  const priceRs = parseFloat(document.getElementById('edit-price').value);
  if(!name||isNaN(priceRs)||priceRs<=0){ toast('Fill in all fields','err'); return; }
  try{
    await api('PATCH',`/admin/products/${id}`,{name,description:desc,price:Math.round(priceRs*100),active:editActive});
    toast('Product updated ✓','ok');
    closeModal();
    loadProducts();
  }catch(e){ toast(e.message,'err'); }
}

async function deleteProduct(id){
  if(!confirm('Delete this product?')) return;
  try{
    await api('DELETE',`/admin/products/${id}`);
    toast('Deleted','ok');
    loadProducts();
  }catch(e){ toast(e.message,'err'); }
}

async function loadPurchases(){
  try{
    const data = await api('GET','/admin/purchases');
    const tbody = document.getElementById('purchases-body');
    const purch = data.purchases||[];
    if(!purch.length){
      tbody.innerHTML=`<tr><td colspan="6"><div class="empty"><div class="empty-icon">💳</div>No purchases yet</div></td></tr>`;
      return;
    }
    tbody.innerHTML = purch.map(p=>`
      <tr>
        <td>${esc(p.customer_name||'—')}</td>
        <td style="font-size:.82rem;color:var(--muted)">${esc(p.customer_email||'—')}</td>
        <td class="price-cell">₹${((p.amount||0)/100).toFixed(2)}</td>
        <td><span class="status-${p.status}">${p.status}</span></td>
        <td class="mono">${(p.razorpay_order_id||'—').substring(0,18)}…</td>
        <td class="mono">${p.created_at?new Date(p.created_at).toLocaleDateString():'—'}</td>
      </tr>`).join('');
  }catch(e){ toast(e.message,'err'); }
}

let toastTimer;
function toast(msg, type='ok'){
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show '+type;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(()=>el.className='', 3000);
}

function esc(s){ const d=document.createElement('div');d.textContent=s;return d.innerHTML; }

// close modal on backdrop click
document.getElementById('edit-modal').addEventListener('click', e => {
  if(e.target===e.currentTarget) closeModal();
});
</script>
</body>
</html>"""