import os, sqlite3, secrets, hmac, re
from datetime import date, timedelta
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, session, abort, send_from_directory, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from pypdf import PdfReader
app=Flask(__name__)
app.secret_key=os.environ['SECRET_KEY']; app.config.update(MAX_CONTENT_LENGTH=15*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('SECURE_COOKIE','1')=='1')
root=Path(os.getenv('DATA_DIR','data')); root.mkdir(exist_ok=True); (root/'uploads').mkdir(exist_ok=True)
def db():
 c=sqlite3.connect(root/'app.db'); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c
with db() as c:
 c.executescript('''CREATE TABLE IF NOT EXISTS vendors(id INTEGER PRIMARY KEY,name TEXT NOT NULL,email TEXT,broker TEXT,token TEXT UNIQUE,limit_required INTEGER DEFAULT 1000000,umbrella INTEGER DEFAULT 0,additional INTEGER DEFAULT 1,created TEXT); CREATE TABLE IF NOT EXISTS docs(id INTEGER PRIMARY KEY,vendor INTEGER REFERENCES vendors(id),kind TEXT,filename TEXT,stored TEXT,expiry TEXT,coverage INTEGER,umbrella INTEGER,additional INTEGER DEFAULT 0,status TEXT DEFAULT 'Pending',notes TEXT,extracted TEXT,created TEXT); CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,vendor INTEGER,action TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP);''')
def log(c,v,a): c.execute('INSERT INTO audit(vendor,action) VALUES(?,?)',(v,a))
def csrf():
 if 'csrf' not in session: session['csrf']=secrets.token_urlsafe(32)
 return session['csrf']
app.jinja_env.globals['csrf']=csrf
@app.before_request
def guard():
 if request.method=='POST' and not hmac.compare_digest(request.form.get('csrf',''),session.get('csrf','!')): abort(400)
 if request.endpoint not in ('login','portal','static') and not session.get('admin'): return redirect(url_for('login'))
@app.route('/login',methods=['GET','POST'])
def login():
 if request.method=='POST':
  if hmac.compare_digest(request.form.get('password',''),os.environ['ADMIN_PASSWORD']): session.clear(); session['admin']=True; return redirect('/')
  flash('Invalid password')
 return render_template('login.html')
@app.post('/logout')
def logout(): session.clear(); return redirect('/login')
def vendor(c,i):
 v=c.execute('SELECT * FROM vendors WHERE id=?',(i,)).fetchone()
 if not v: abort(404)
 return v
def clearance(v,docs):
 today=date.today().isoformat(); missing=[]
 for kind in ('COI','W-9','Lien waiver'):
  valid=[d for d in docs if d['kind']==kind and d['status']=='Approved' and (kind!='COI' or (d['expiry'] and d['expiry']>=today and (d['coverage'] or 0)>=v['limit_required'] and (d['umbrella'] or 0)>=v['umbrella'] and (not v['additional'] or d['additional'])))]
  if not valid: missing.append(kind)
 return missing
@app.get('/')
def home():
 with db() as c:
  rows=[]
  for v in c.execute('SELECT * FROM vendors ORDER BY id DESC'):
   ds=c.execute('SELECT * FROM docs WHERE vendor=?',(v['id'],)).fetchall(); missing=gaps(c,v); exp=any(d['kind']=='COI' and d['status']=='Approved' and d['expiry'] and date.today().isoformat()<=d['expiry']<=(date.today()+timedelta(days=30)).isoformat() for d in ds); rows.append((v,missing,exp))
 return render_template('home.html',rows=rows)
@app.post('/vendors')
def add():
 name=request.form['name'].strip();
 if not name: abort(400)
 with db() as c:
  cur=c.execute('INSERT INTO vendors(name,email,broker,token,limit_required,umbrella,additional,created) VALUES(?,?,?,?,?,?,?,?)',(name,request.form.get('email'),request.form.get('broker'),secrets.token_urlsafe(32),max(0,int(request.form.get('limit',1000000))),max(0,int(request.form.get('umbrella',0))),int('additional' in request.form),date.today().isoformat())); log(c,cur.lastrowid,'Vendor created')
 return redirect('/')
@app.get('/vendors/<int:i>')
def detail(i):
 with db() as c:
  v=vendor(c,i); ds=c.execute('SELECT * FROM docs WHERE vendor=? ORDER BY id DESC',(i,)).fetchall(); events=c.execute('SELECT * FROM audit WHERE vendor=? ORDER BY id DESC',(i,)).fetchall()
 return render_template('detail.html',v=v,docs=ds,missing=gaps(c,v),events=events)
@app.post('/vendors/<int:i>/rotate')
def rotate(i):
 with db() as c: vendor(c,i); c.execute('UPDATE vendors SET token=? WHERE id=?',(secrets.token_urlsafe(32),i)); log(c,i,'Upload link rotated')
 return redirect(url_for('detail',i=i))
@app.route('/portal/<token>',methods=['GET','POST'])
def portal(token):
 with db() as c:
  v=c.execute('SELECT * FROM vendors WHERE token=?',(token,)).fetchone()
  if not v: abort(404)
  if request.method=='POST':
   f=request.files.get('file'); kind=request.form.get('kind');
   if not f or kind not in ('COI','W-9','Lien waiver','Endorsement','License') or not f.filename.lower().endswith('.pdf'): abort(400)
   if f.stream.read(5)!=b'%PDF-': abort(400)
   f.stream.seek(0); stored=secrets.token_hex(24)+'.pdf'; path=root/'uploads'/stored; f.save(path)
   try: reader=PdfReader(path); extracted='\n'.join((p.extract_text() or '') for p in reader.pages[:20])[:30000]
   except Exception: extracted='Text extraction unavailable; manual review required.'
   c.execute('INSERT INTO docs(vendor,kind,filename,stored,extracted,created) VALUES(?,?,?,?,?,?)',(v['id'],kind,secure_filename(f.filename),stored,extracted,date.today().isoformat())); log(c,v['id'],kind+' uploaded'); flash('Document received. Awaiting review.'); return redirect(url_for('portal',token=token))
 return render_template('portal.html',v=v)
@app.post('/docs/<int:i>/review')
def review(i):
 with db() as c:
  d=c.execute('SELECT * FROM docs WHERE id=?',(i,)).fetchone()
  if not d: abort(404)
  status=request.form['status']; expiry=request.form.get('expiry') or None
  if status not in ('Approved','Rejected','Pending'): abort(400)
  if expiry: date.fromisoformat(expiry)
  c.execute('UPDATE docs SET status=?,expiry=?,coverage=?,umbrella=?,additional=?,notes=?,workers=?,auto=? WHERE id=?',(status,expiry,max(0,int(request.form.get('coverage') or 0)),max(0,int(request.form.get('umbrella') or 0)),int('additional' in request.form),request.form.get('notes',''),number('workers'),number('auto'),i)); log(c,d['vendor'],f"{d['kind']} reviewed: {status}")
 return redirect(url_for('detail',i=d['vendor']))
@app.get('/docs/<int:i>/download')
def download(i):
 with db() as c: d=c.execute('SELECT * FROM docs WHERE id=?',(i,)).fetchone()
 if not d: abort(404)
 return send_from_directory((root/'uploads').resolve(),d['stored'],as_attachment=True,download_name=d['filename'])

# RiskLatch v2: project assignments, invoice review and reminder queue.
import csv, io, smtplib
from email.message import EmailMessage
from flask import Response
with db() as c:
 c.executescript('''CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY,name TEXT NOT NULL,liability INTEGER NOT NULL,umbrella INTEGER NOT NULL,additional INTEGER NOT NULL); CREATE TABLE IF NOT EXISTS assignments(project INTEGER REFERENCES projects(id),vendor INTEGER REFERENCES vendors(id),PRIMARY KEY(project,vendor)); CREATE TABLE IF NOT EXISTS invoices(id INTEGER PRIMARY KEY,vendor INTEGER REFERENCES vendors(id),project INTEGER REFERENCES projects(id),reference TEXT NOT NULL,cents INTEGER NOT NULL,status TEXT DEFAULT 'Pending',notes TEXT DEFAULT '',created TEXT DEFAULT CURRENT_TIMESTAMP); CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY,vendor INTEGER REFERENCES vendors(id),recipient TEXT,subject TEXT,body TEXT,status TEXT DEFAULT 'Queued',created TEXT DEFAULT CURRENT_TIMESTAMP);''')
 for name,definition in [('workers','INTEGER DEFAULT 0'),('auto','INTEGER DEFAULT 0'),('license','INTEGER DEFAULT 0')]:
  if name not in [r[1] for r in c.execute('PRAGMA table_info(vendors)')]: c.execute(f'ALTER TABLE vendors ADD COLUMN {name} {definition}')
 for name in ('workers','auto'):
  if name not in [r[1] for r in c.execute('PRAGMA table_info(docs)')]: c.execute(f'ALTER TABLE docs ADD COLUMN {name} INTEGER DEFAULT 0')

def number(name,default=0):
 try: n=int(request.form.get(name,default)); assert 0<=n<=1000000000; return n
 except (ValueError,AssertionError): abort(400)

def gaps(c,v,p=None,invoice=False):
 ds=c.execute('SELECT * FROM docs WHERE vendor=?',(v['id'],)).fetchall(); today=date.today().isoformat(); out=[]
 liability=max(v['limit_required'],p['liability'] if p else 0); umbrella=max(v['umbrella'],p['umbrella'] if p else 0); additional=v['additional'] or (p and p['additional'])
 cois=[d for d in ds if d['kind']=='COI' and d['status']=='Approved' and d['expiry'] and d['expiry']>=today]
 if not any((d['coverage'] or 0)>=liability and (d['umbrella'] or 0)>=umbrella and (d['workers'] or 0)>=v['workers'] and (d['auto'] or 0)>=v['auto'] and (not additional or d['additional']) for d in cois): out.append('Current COI meeting all coverage and endorsement requirements')
 if not any(d['kind']=='W-9' and d['status']=='Approved' for d in ds): out.append('Approved W-9')
 if v['license'] and not any(d['kind']=='License' and d['status']=='Approved' and d['expiry'] and d['expiry']>=today for d in ds): out.append('Current approved license')
 if invoice: out.append('Invoice-specific lien waiver and contractual payment review required')
 return out

@app.get('/operations')
def operations():
 with db() as c:
  vs=c.execute('SELECT * FROM vendors ORDER BY name').fetchall(); ps=c.execute('SELECT * FROM projects ORDER BY name').fetchall(); assignments=c.execute('SELECT a.*,p.name project_name,v.name vendor_name FROM assignments a JOIN projects p ON p.id=a.project JOIN vendors v ON v.id=a.vendor').fetchall(); invoices=c.execute('SELECT i.*,v.name vendor_name,p.name project_name FROM invoices i JOIN vendors v ON v.id=i.vendor JOIN projects p ON p.id=i.project ORDER BY i.id DESC').fetchall(); reminders=c.execute('SELECT * FROM reminders ORDER BY id DESC LIMIT 100').fetchall(); risks=[(v,gaps(c,v)) for v in vs]; project_risks=[(a,gaps(c,vendor(c,a['vendor']),c.execute('SELECT * FROM projects WHERE id=?',(a['project'],)).fetchone())) for a in assignments]; exp=c.execute("SELECT d.*,v.name vendor_name FROM docs d JOIN vendors v ON v.id=d.vendor WHERE d.status='Approved' AND d.expiry IS NOT NULL AND d.expiry<=? ORDER BY d.expiry",((date.today()+timedelta(days=60)).isoformat(),)).fetchall()
 return render_template('operations.html',vs=vs,ps=ps,assignments=assignments,invoices=invoices,reminders=reminders,risks=risks,project_risks=project_risks,exp=exp)
@app.post('/projects')
def create_project():
 name=request.form.get('name','').strip();
 if not name: abort(400)
 with db() as c: c.execute('INSERT INTO projects(name,liability,umbrella,additional) VALUES(?,?,?,?)',(name,number('liability'),number('umbrella'),int('additional' in request.form)))
 return redirect('/operations')
@app.post('/assignments')
def assign():
 with db() as c:
  v=vendor(c,number('vendor')); p=number('project');
  if not c.execute('SELECT 1 FROM projects WHERE id=?',(p,)).fetchone(): abort(404)
  c.execute('INSERT OR IGNORE INTO assignments VALUES(?,?)',(p,v['id'])); log(c,v['id'],f'Assigned to project {p}')
 return redirect('/operations')
@app.post('/vendors/<int:i>/requirements')
def requirements(i):
 with db() as c:
  vendor(c,i); c.execute('UPDATE vendors SET limit_required=?,umbrella=?,additional=?,workers=?,auto=?,license=? WHERE id=?',(number('liability'),number('umbrella'),int('additional' in request.form),number('workers'),number('auto'),int('license' in request.form),i)); log(c,i,'Requirements updated')
 return redirect(url_for('detail',i=i))
@app.post('/invoices')
def invoice():
 v=number('vendor'); p=number('project'); ref=request.form.get('reference','').strip(); cents=number('cents');
 if not ref or not cents: abort(400)
 with db() as c:
  if not c.execute('SELECT 1 FROM assignments WHERE project=? AND vendor=?',(p,v)).fetchone(): abort(400,'Assign vendor to project first')
  c.execute('INSERT INTO invoices(vendor,project,reference,cents) VALUES(?,?,?,?)',(v,p,ref,cents)); log(c,v,'Invoice queued: '+ref)
 return redirect('/operations')
@app.post('/invoices/<int:i>/decision')
def decision(i):
 with db() as c:
  inv=c.execute('SELECT * FROM invoices WHERE id=?',(i,)).fetchone()
  if not inv: abort(404)
  status=request.form.get('status'); notes=request.form.get('notes','').strip(); p=c.execute('SELECT * FROM projects WHERE id=?',(inv['project'],)).fetchone()
  if status not in ('Pending','Review needed','Recommended for payment') or not notes: abort(400)
  if status=='Recommended for payment' and (gaps(c,vendor(c,inv['vendor']),p) or 'waiver' not in request.form): abort(400,'Resolve compliance gaps and attest invoice-specific waiver review first')
  c.execute('UPDATE invoices SET status=?,notes=? WHERE id=?',(status,notes,i)); log(c,inv['vendor'],f'Invoice {inv["reference"]}: {status}; {notes}')
 return redirect('/operations')
@app.post('/reminders/queue')
def queue():
 with db() as c:
  for v in c.execute('SELECT * FROM vendors').fetchall():
   missing=gaps(c,v); soon=c.execute("SELECT expiry FROM docs WHERE vendor=? AND kind='COI' AND status='Approved' AND expiry BETWEEN ? AND ?",(v['id'],date.today().isoformat(),(date.today()+timedelta(days=30)).isoformat())).fetchall(); recipient=v['broker'] or v['email'];
   if not recipient or not (missing or soon): continue
   if c.execute("SELECT 1 FROM reminders WHERE vendor=? AND created>=datetime('now','-7 days')",(v['id'],)).fetchone(): continue
   body='Please review the following compliance items for '+v['name']+':\n'+'\n'.join(missing+['COI expiration: '+r['expiry'] for r in soon])+'\nUpload: '+os.getenv('PUBLIC_BASE_URL','').rstrip('/')+'/portal/'+v['token']; c.execute('INSERT INTO reminders(vendor,recipient,subject,body) VALUES(?,?,?,?)',(v['id'],recipient,'RiskLatch compliance update',body)); log(c,v['id'],'Reminder queued')
 return redirect('/operations')
@app.post('/reminders/<int:i>/send')
def send_reminder(i):
 if not os.getenv('SMTP_HOST') or not os.getenv('SMTP_FROM') or not os.getenv('PUBLIC_BASE_URL','').startswith('https://'): abort(400,'Configure SMTP and HTTPS PUBLIC_BASE_URL first')
 with db() as c:
  r=c.execute('SELECT * FROM reminders WHERE id=?',(i,)).fetchone()
  if not r or r['status']!='Queued': abort(400)
  msg=EmailMessage(); msg['From']=os.environ['SMTP_FROM']; msg['To']=r['recipient']; msg['Subject']=r['subject']; msg.set_content(r['body'].split('\nUpload:')[0]+'\nUpload: '+os.environ['PUBLIC_BASE_URL'].rstrip('/')+'/portal/'+vendor(c,r['vendor'])['token'])
  try:
   with smtplib.SMTP(os.environ['SMTP_HOST'],int(os.getenv('SMTP_PORT','587')),timeout=15) as smtp:
    smtp.starttls();
    if os.getenv('SMTP_USER'): smtp.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
    smtp.send_message(msg)
  except (OSError,smtplib.SMTPException): flash('Email failed; check SMTP settings.'); return redirect('/operations')
  c.execute("UPDATE reminders SET status='Sent' WHERE id=?",(i,)); log(c,r['vendor'],'Reminder sent')
 return redirect('/operations')
@app.get('/reports/compliance.csv')
def report():
 out=io.StringIO(); w=csv.writer(out); w.writerow(['Vendor','Project','Status','Deficiencies']);
 def safe(s): return "'"+s if s.startswith(('=','+','-','@','\t','\r')) else s
 with db() as c:
  for v in c.execute('SELECT * FROM vendors').fetchall():
   ps=c.execute('SELECT p.* FROM projects p JOIN assignments a ON a.project=p.id WHERE a.vendor=?',(v['id'],)).fetchall() or [None]
   for p in ps:
    g=gaps(c,v,p); w.writerow([safe(v['name']),safe(p['name']) if p else '', 'Review needed' if g else 'Checklist clear','; '.join(g)])
 return Response(out.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=risklatch-compliance.csv'})
