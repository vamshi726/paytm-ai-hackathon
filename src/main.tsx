import React, {useEffect, useMemo, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ArrowUpRight, Bell, Bot, CheckCircle2, ChevronRight, CircleHelp, CreditCard, Headphones, Home, Menu, MessageCircle, Search, Send, ShieldCheck, Smartphone, Ticket, Wallet} from 'lucide-react';
import './styles.css';

const API='http://localhost:8000/api';
type Message={sender_type:string;message:string;created_at:string};
type Case={id:string;category:string;issue_type:string;transaction_id?:string;risk_level:string;status:string;description:string;updated_at:string;resolution?:string};
const quick=['Where is my ₹799 UPI reversal?','I was charged twice ₹5,000','I don’t recognize a ₹20,000 UPI transfer','My recharge is pending'];
const money=(n?:number)=>n ? `₹${n.toLocaleString('en-IN')}` : '—';
function Status({children}:{children:string}){return <span className={'status '+children.toLowerCase().replaceAll(' ','-')}>{children}</span>}
function App(){const [page,setPage]=useState<'chat'|'dashboard'>('chat'); return <>{page==='chat'?<Chat goDashboard={()=>setPage('dashboard')}/>:<Dashboard goChat={()=>setPage('chat')}/>}</>}
function Shell({children,active,goChat,goDashboard}:{children:React.ReactNode;active:string;goChat:()=>void;goDashboard:()=>void}){return <div className="app"><aside><div className="brand"><div className="brand-mark">S</div><span>saathi</span></div><nav><button className={active==='chat'?'active':''} onClick={goChat}><MessageCircle/> Support chat</button><button className={active==='dashboard'?'active':''} onClick={goDashboard}><Home/> Operations</button></nav><div className="prototype"><ShieldCheck/><div><b>Prototype mode</b><small>All actions are simulated</small></div></div></aside><main>{children}</main></div>}
function Chat({goDashboard}:{goDashboard:()=>void}){const [messages,setMessages]=useState<Message[]>([{sender_type:'assistant',message:'Hi Chetan! I’m Saathi, your support companion. I can investigate payments, recharges, bookings, and account concerns.',created_at:new Date().toISOString()}]);const [text,setText]=useState('');const [caseId,setCaseId]=useState<string>();const [status,setStatus]=useState('Ready to help');const [approval,setApproval]=useState<any>();const [syncError,setSyncError]=useState('');
const send=async (value=text)=>{if(!value.trim())return;setText('');setMessages(m=>[...m,{sender_type:'customer',message:value,created_at:new Date().toISOString()}]);setStatus('Understanding your issue…'); const r=await fetch(API+'/chat/message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:value,case_id:caseId})});const d=await r.json();setCaseId(d.case_id);setApproval(d.approval);setStatus(d.status);setMessages(m=>[...m,{sender_type:'assistant',message:d.message,created_at:new Date().toISOString()}]);};
useEffect(()=>{
  if(!caseId||approval?.status!=='PENDING')return;
  let cancelled=false;
  const refresh=async()=>{
    try{
      const response=await fetch(`${API}/cases/${caseId}`);
      if(!response.ok)throw new Error('Case refresh failed');
      const data=await response.json();
      if(cancelled)return;
      const current=data.approvals.find((item:any)=>item.id===approval.id);
      if(!current)throw new Error('Approval not found');
      setMessages((existing)=>{
        const greeting=existing.find(message=>message.sender_type==='assistant'&&message.message.startsWith('Hi Chetan!'));
        return greeting?[greeting,...data.messages]:data.messages;
      });
      setStatus(data.case.status);
      setApproval((existing:any)=>existing?{...existing,...current,action:existing.action||current.proposed_action}:existing);
      setSyncError('');
    }catch{
      if(!cancelled)setSyncError('Could not refresh the case. Keep this page open while the approval is pending.');
    }
  };
  void refresh();
  const timer=window.setInterval(()=>void refresh(),5000);
  return ()=>{cancelled=true;window.clearInterval(timer);};
},[approval?.id,approval?.status,caseId]);
return <Shell active="chat" goChat={()=>{}} goDashboard={goDashboard}><header><div><p className="eyebrow">PAYMENT SUPPORT</p><h1>How can we help?</h1></div><div className="header-actions"><button className="icon"><Search/></button><button className="avatar">CK</button></div></header><div className="chat-layout"><section className="conversation"><div className="welcome-card"><div><p>SAATHI ASSIST</p><h2>Support that follows through.</h2><span>Tell us what went wrong. Saathi checks the details and keeps you updated.</span></div><Bot/></div><div className="case-strip"><span className="pulse"/>{status}{caseId&&<><i/> <b>{caseId}</b></>}</div><div className="messages">{messages.map((m,i)=><div key={i} className={'message '+m.sender_type}><div className="bubble">{m.message}</div><small>{m.sender_type==='customer'?'You':'Saathi'} · {new Date(m.created_at).toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'})}</small></div>)}</div>{syncError&&<p role="status">{syncError}</p>}{approval&&<div className="approval-card"><div className="approval-icon"><Bell/></div><div><b>{approval.status==='PENDING'?'Human review requested':`Human review ${String(approval.status).toLowerCase()}`}</b><p>{approval.status==='PENDING'?`${approval.action}. Waiting for the approver’s email reply.`:`Decision received${approval.reviewer_comments?`: Approver comment: ${approval.reviewer_comments}`:''}.`}</p></div><button onClick={goDashboard}>View case <ChevronRight/></button></div>}<div className="quick">{quick.map(q=><button key={q} onClick={()=>send(q)}>{q}</button>)}</div><form onSubmit={e=>{e.preventDefault();send()}}><input value={text} onChange={e=>setText(e.target.value)} placeholder="Describe an issue or paste a transaction ID…"/><button aria-label="Send"><Send/></button></form></section><aside className="help-panel"><h3>Popular help</h3><button><Wallet/>UPI payments <ChevronRight/></button><button><Smartphone/>Recharge & bills <ChevronRight/></button><button><Ticket/>Travel & bookings <ChevronRight/></button><button><CreditCard/>Loans & cards <ChevronRight/></button><div className="need-help"><CircleHelp/><b>Need urgent help?</b><p>Report suspected fraud right away. Saathi will create a security case.</p></div></aside></div></Shell>}
function Dashboard({goChat}:{goChat:()=>void}) {
  const [cases,setCases]=useState<Case[]>([]);
  const [summary,setSummary]=useState<any>({});
  const [approvalCaseIds,setApprovalCaseIds]=useState<Set<string>>(new Set());
  const [selected,setSelected]=useState<any>();
  const [tab,setTab]=useState<'queue'|'approvals'>('queue');
  const [refreshError,setRefreshError]=useState('');
  const load=async()=>{
    try{
      const [caseResponse,summaryResponse,approvalResponse]=await Promise.all([
        fetch(API+'/cases'),
        fetch(API+'/dashboard/summary'),
        fetch(API+'/approvals')
      ]);
      if(!caseResponse.ok||!summaryResponse.ok||!approvalResponse.ok)throw new Error('Dashboard refresh failed');
      const [c,s,a]=await Promise.all([caseResponse.json(),summaryResponse.json(),approvalResponse.json()]);
      setCases(c);
      setSummary(s);
      setApprovalCaseIds(new Set(a.map((item:any)=>item.case_id)));
      if(selected){
        const detailResponse=await fetch(API+'/cases/'+selected.case.id);
        if(!detailResponse.ok)throw new Error('Case refresh failed');
        setSelected(await detailResponse.json());
      }
      setRefreshError('');
    }catch{
      setRefreshError('Could not refresh operations data. Check that the backend is running.');
    }
  };
  useEffect(()=>{
    void load();
    const timer=window.setInterval(()=>void load(),5000);
    return ()=>window.clearInterval(timer);
  },[selected?.case.id]);
  const show=async(id:string)=>setSelected(await fetch(API+'/cases/'+id).then(r=>r.json()));
  return <Shell active="dashboard" goChat={goChat} goDashboard={()=>{}}>
    <header>
      <div><p className="eyebrow">SAATHI OPERATIONS</p><h1>Support command center</h1></div>
      <div className="header-actions"><button className="icon"><Search/></button><button className="avatar">SR</button></div>
    </header>
    <section className="metrics">
      <Metric label="Total cases" value={summary.total||0} icon={<MessageCircle/>}/>
      <Metric label="Open cases" value={summary.open||0} icon={<Headphones/>}/>
      <Metric label="Awaiting review" value={summary.pending_approvals||0} icon={<Bell/>}/>
      <Metric label="Resolved" value={summary.resolved||0} icon={<CheckCircle2/>}/>
    </section>
    {refreshError&&<p role="status">{refreshError}</p>}
    <div className="tabs">
      <button className={tab==='queue'?'selected':''} onClick={()=>setTab('queue')}>Case queue</button>
      <button className={tab==='approvals'?'selected':''} onClick={()=>setTab('approvals')}>Human approvals</button>
    </div>
    <section className="operations">
      <div className="case-list">
        <div className="list-head">
          <div><h2>{tab==='queue'?'Active support cases':'Approval requests'}</h2><span>{cases.length} cases in workspace</span></div>
          <button className="filter"><Menu/> Filters</button>
        </div>
        {cases.filter(c=>tab==='queue'||approvalCaseIds.has(c.id)).map(c=>
          <button className={'case-row '+(selected?.case.id===c.id?'chosen':'')} key={c.id} onClick={()=>show(c.id)}>
            <div className="case-title"><b>{c.id}</b><Status>{c.status}</Status></div>
            <span>{c.issue_type} · {c.category}</span>
            <small>{c.transaction_id||'No transaction selected'} · <em>{c.risk_level} risk</em></small>
          </button>
        )}
      </div>
      <div className="case-detail">
        {!selected?<div className="empty"><Bot/><h2>Select a case</h2><p>Review the investigation, evidence, and customer history.</p></div>:<>
          <div className="detail-top">
            <div><p className="eyebrow">{selected.case.id}</p><h2>{selected.case.issue_type}</h2><span>{selected.case.category}</span></div>
            <Status>{selected.case.status}</Status>
          </div>
          <div className="detail-section">
            <h3>Customer-facing resolution</h3>
            <p>{selected.case.resolution||'Investigation in progress.'}</p>
          </div>
          <div className="detail-section">
            <h3>AI investigation</h3>
            {selected.investigation.length?selected.investigation.map((x:any,i:number)=>
              <div className="evidence" key={i}><span><ShieldCheck/></span><div><b>{x.tool_name}</b><p>{x.sanitized_output}</p></div></div>
            ):<p>No tool checks have been run yet.</p>}
          </div>
          {selected.approvals.map((a:any)=><div className="decision" key={a.id}>
            <div>
              <p className="eyebrow">{a.risk_level} RISK · {a.status}</p>
              <h3>{a.proposed_action}</h3>
              <span>Requested {new Date(a.requested_at).toLocaleString()}</span>
            </div>
            {a.status==='PENDING'&&<p className="comment">
              Waiting for the approver’s email reply.
              Deadline: {a.expires_at?new Date(a.expires_at).toLocaleString():'within 20 minutes'}.
            </p>}
            {a.reviewer_id&&a.status!=='PENDING'&&<p className="comment">Decision received from {a.reviewer_id} at {a.decision_at?new Date(a.decision_at).toLocaleString():'an unknown time'}.</p>}
            {a.reviewer_comments&&<p className="comment">“{a.reviewer_comments}”</p>}
          </div>)}
          <div className="detail-section">
            <h3>Activity timeline</h3>
            {selected.activities.map((a:any,i:number)=>
              <div className="timeline" key={i}><span/><div><b>{a.description}</b><small>{a.actor_id} · {new Date(a.created_at).toLocaleString()}</small></div></div>
            )}
          </div>
        </>}
      </div>
    </section>
  </Shell>
}
function Metric({label,value,icon}:{label:string;value:number;icon:React.ReactNode}){return <div className="metric"><span>{icon}</span><div><p>{label}</p><b>{value}</b></div></div>}; createRoot(document.getElementById('root')!).render(<App/>);
