import React, { useState, useEffect } from 'react';
import ormService from '../../services/ormService';
import { useAuth } from '../../context/AuthContext';
import { useNotification } from '../../context/NotificationContext';
import { Users, Eye, Edit3, Shield, Lock, Unlock, UserCheck, X, Plus, Layers, Trash2, Bell, Settings2 } from 'lucide-react';
import axios from 'axios';

const ORMTemplateManager = () => {
  const [templates, setTemplates] = useState([]);
  const [users, setUsers] = useState([]);
  const [isAdding, setIsAdding] = useState(false);
  const [editingNode, setEditingNode] = useState(null); // {node, path}
  const [editingTemplate, setEditingTemplate] = useState(null); // template being edited
  const [showReminderModal, setShowReminderModal] = useState(null); // template for reminder config
  const [viewingTemplate, setViewingTemplate] = useState(null); // template for tabular report view
  const [tempAchievements, setTempAchievements] = useState({}); // { nodeName_depth: value }
  const [newTemplate, setNewTemplate] = useState({
    name: '',
    description: '',
    category: '',
    structure: [
      { name: 'Revenue', weightage: 30, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
      { name: 'Process', weightage: 20, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
      { name: 'Customer', weightage: 20, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
      { name: 'Team', weightage: 15, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: true, children: [] },
      { name: 'Cost', weightage: 15, formula_type: 'reverse', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] }
    ]
  });

  const { showSuccess, showError } = useNotification();
  const { user } = useAuth();

  useEffect(() => {
    loadTemplates();
    loadUsers();
  }, []);

  const loadTemplates = async () => {
    try {
      const data = await ormService.getTemplates();
      setTemplates(data);
    } catch (error) {
      showError('Failed to load templates');
    }
  };

  const loadUsers = async () => {
    try {
      const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';
      const response = await axios.get(`${API_URL}/users?active_only=true`);
      setUsers(response.data);
    } catch (error) {
      console.error('Failed to load users');
    }
  };

  const handleSave = async () => {
    try {
      const totalWeight = newTemplate.structure.reduce((sum, item) => sum + item.weightage, 0);
      if (Math.abs(totalWeight - 100) > 0.01) {
        showError('Total weightage must be 100%');
        return;
      }
      const payload = {
        ...newTemplate,
        company_id: user?.company_id || 'default' // Ensure company_id is provided
      };
      
      if (editingTemplate) {
        await ormService.updateTemplate(editingTemplate._id, payload);
        showSuccess('Template updated successfully');
      } else {
        await ormService.createTemplate(payload);
        showSuccess('Template created successfully');
      }
      
      setIsAdding(false);
      setEditingTemplate(null);
      loadTemplates();
    } catch (error) {
      showError('Failed to save template');
    }
  };

  const handleDeleteTemplate = async (id) => {
    if (!window.confirm('Are you sure you want to delete this template?')) return;
    try {
      await ormService.deleteTemplate(id);
      showSuccess('Template deleted');
      loadTemplates();
    } catch (error) {
      showError('Delete failed');
    }
  };

  const handleEditTemplate = (template) => {
    setNewTemplate({
      name: template.name,
      description: template.description || '',
      category: template.category || '',
      structure: template.structure,
      reminder_config: template.reminder_config || { enabled: false, day_of_month: 25, message: '' }
    });
    setEditingTemplate(template);
    setIsAdding(true);
  };

  const updateNode = (path, updates) => {
    const updatedStructure = [...newTemplate.structure];
    let current = updatedStructure;

    // Navigate to the correct node
    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]].children;
    }

    const lastIdx = path[path.length - 1];
    current[lastIdx] = { ...current[lastIdx], ...updates };

    setNewTemplate({ ...newTemplate, structure: updatedStructure });
  };
  const removeNode = (path) => {
    const updatedStructure = [...newTemplate.structure];
    let current = updatedStructure;
    
    for (let i = 0; i < path.length - 1; i++) {
      current = current[path[i]].children;
    }
    
    const lastIdx = path[path.length - 1];
    current.splice(lastIdx, 1);
    
    setNewTemplate({ ...newTemplate, structure: updatedStructure });
  };

  const renderNode = (node, index, path = []) => {
    const currentPath = [...path, index];
    const isRestricted = node.allowed_fillers?.length > 0 || node.allowed_viewers?.length > 0;

    const nodeKey = currentPath.join('-');

    return (
      <div key={nodeKey} className="ml-5 border-l border-slate-200 pl-3 py-2 mt-2 relative">
        <div className={`flex items-center gap-3 bg-white p-3 rounded-xl shadow-sm border ${isRestricted ? 'border-amber-200 bg-amber-50/20' : 'border-slate-100'} hover:border-indigo-300 transition-all`}>
          <div className="flex-1 flex items-center gap-2">
            {node.is_anonymous ? <Lock size={12} className="text-amber-500" /> : <Shield size={12} className="text-indigo-500" />}
            <input
              type="text"
              value={node.name}
              onChange={(e) => updateNode(currentPath, { name: e.target.value })}
              className="bg-transparent border-none focus:ring-0 font-bold text-slate-800 text-xs w-full p-0"
              placeholder="Item Name"
            />
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-slate-50 px-2 py-0.5 rounded-lg border border-slate-100">
              <span className="text-[8px] text-slate-400 font-black uppercase">Weight</span>
              <input
                type="number"
                value={node.weightage}
                onChange={(e) => updateNode(currentPath, { weightage: parseFloat(e.target.value) || 0 })}
                className="w-10 bg-transparent border-none text-[11px] font-black text-slate-700 p-0 focus:ring-0 text-center"
              />
            </div>

            <div className="flex items-center gap-1.5 bg-indigo-50/30 px-2 py-0.5 rounded-lg border border-indigo-100">
              <span className="text-[8px] text-indigo-600 font-black uppercase">Target</span>
              <input
                type="number"
                value={node.target_value}
                onChange={(e) => updateNode(currentPath, { target_value: parseFloat(e.target.value) || 0 })}
                className="w-12 bg-transparent border-none text-[11px] font-black text-indigo-700 p-0 focus:ring-0 text-center"
              />
            </div>

            <select
              value={node.formula_type}
              onChange={(e) => updateNode(currentPath, { formula_type: e.target.value })}
              className="bg-slate-50 border-slate-100 rounded-lg text-[9px] font-black px-2 py-0.5 text-slate-500 focus:ring-indigo-500 outline-none uppercase tracking-tighter"
            >
              <option value="standard">STD</option>
              <option value="reverse">REV</option>
            </select>

            <div className="flex items-center gap-1">
              <button
                onClick={() => setEditingNode({ node, path: currentPath })}
                className={`p-1.5 rounded-lg transition-all ${isRestricted ? 'bg-amber-100 text-amber-600' : 'bg-slate-100 text-slate-400 hover:bg-indigo-100 hover:text-indigo-600'}`}
                title="Permissions"
              >
                <Users size={12} />
              </button>
              <button
                onClick={() => {
                  const newNode = { 
                    name: 'New Sub-item', 
                    weightage: 0, 
                    formula_type: 'standard', 
                    target_value: 0,
                    unit: '',
                    allowed_fillers: [],
                    allowed_viewers: [],
                    is_anonymous: false,
                    children: [] 
                  };
                  updateNode(currentPath, { children: [...(node.children || []), newNode] });
                }}
                className="p-1.5 bg-indigo-50 text-indigo-600 rounded-lg hover:bg-indigo-600 hover:text-white transition-all"
                title="Add Child"
              >
                <Plus size={12} />
              </button>
              <button 
                onClick={() => removeNode(currentPath)}
                className="p-1.5 bg-rose-50 text-rose-600 rounded-lg hover:bg-rose-600 hover:text-white transition-all"
                title="Remove Item"
              >
                <Trash2 size={12} />
              </button>
            </div>
          </div>
        </div>

        {isRestricted && (
          <div className="mt-1 flex gap-1.5 ml-2">
            {node.allowed_fillers?.length > 0 && <span className="text-[8px] font-black bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded-md uppercase flex items-center gap-1 leading-none"><Edit3 size={8} /> {node.allowed_fillers.length} Fillers</span>}
            {node.allowed_viewers?.length > 0 && <span className="text-[8px] font-black bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-md uppercase flex items-center gap-1 leading-none"><Eye size={8} /> {node.allowed_viewers.length} Viewers</span>}
          </div>
        )}

        {node.children && node.children.map((child, cIdx) => renderNode(child, cIdx, currentPath))}
      </div>
    );
  };

  return (
    <div className="p-6 bg-slate-50 min-h-screen">
      <div className="max-w-6xl mx-auto">
        <header className="flex justify-between items-center mb-6">
          <div>
            <h1 className="text-2xl font-bold text-slate-800">Outcome Result Management</h1>
            <p className="text-slate-500 text-sm mt-1">Configure performance tracking templates for your company.</p>
          </div>
          <button
            onClick={() => {
              setEditingTemplate(null);
              setNewTemplate({
                name: '',
                description: '',
                category: '',
                structure: [
                  { name: 'Revenue', weightage: 30, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
                  { name: 'Process', weightage: 20, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
                  { name: 'Customer', weightage: 20, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] },
                  { name: 'Team', weightage: 15, formula_type: 'standard', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: true, children: [] },
                  { name: 'Cost', weightage: 15, formula_type: 'reverse', target_value: 0, unit: '', allowed_fillers: [], allowed_viewers: [], is_anonymous: false, children: [] }
                ]
              });
              setIsAdding(true);
            }}
            className="bg-indigo-600 hover:bg-indigo-700 text-white px-5 py-2.5 rounded-xl font-bold shadow-lg shadow-indigo-100 transition-all flex items-center gap-2 text-sm"
          >
            <Plus size={18} />
            New Template
          </button>
        </header>

        {isAdding ? (
          <div className="bg-white rounded-2xl shadow-xl border border-slate-200 overflow-hidden">
            <div className="p-5 border-b border-slate-100 bg-slate-50/50">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 ml-1">Template Name</label>
                  <input
                    type="text"
                    value={newTemplate.name}
                    onChange={(e) => setNewTemplate({ ...newTemplate, name: e.target.value })}
                    className="w-full bg-white border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 transition-all font-bold"
                    placeholder="e.g. Sales Q1 Performance"
                  />
                </div>
                <div>
                  <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 ml-1">Category</label>
                  <input
                    type="text"
                    value={newTemplate.category}
                    onChange={(e) => setNewTemplate({ ...newTemplate, category: e.target.value })}
                    className="w-full bg-white border-slate-200 rounded-xl px-4 py-2.5 text-sm focus:ring-2 focus:ring-indigo-500 transition-all font-bold"
                    placeholder="e.g. Sales / Operations"
                  />
                </div>
              </div>
            </div>

            <div className="p-6">
              <h3 className="text-base font-bold text-slate-800 mb-4 flex items-center gap-2">
                <Layers size={18} className="text-indigo-600" />
                Structure & Weightage
              </h3>

              <div className="space-y-3">
                {newTemplate.structure.map((node, idx) => renderNode(node, idx))}
              </div>

              <div className="mt-8 pt-6 border-t border-slate-100 flex justify-end gap-3">
                <button
                  onClick={() => setIsAdding(false)}
                  className="px-5 py-2.5 rounded-xl font-bold text-slate-500 hover:bg-slate-100 transition-all text-sm"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSave}
                  className="bg-indigo-600 hover:bg-indigo-700 text-white px-6 py-2.5 rounded-xl font-bold shadow-lg shadow-indigo-100 transition-all text-sm"
                >
                  Save Template
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {templates.map((template, tIdx) => (
              <div key={template._id || tIdx} className="bg-white p-5 rounded-2xl shadow-sm border border-slate-200 hover:shadow-md transition-all group flex flex-col relative overflow-hidden">
                {/* Status Badge */}
                <div className="absolute top-0 right-0 px-3 py-1 bg-indigo-50 text-indigo-600 text-[10px] font-bold rounded-bl-xl border-l border-b border-indigo-100">
                  {template.is_active ? 'ACTIVE' : 'INACTIVE'}
                </div>

                <div className="flex justify-between items-start mb-3">
                  <div className="bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-lg text-[9px] font-black uppercase tracking-widest">
                    {template.category || 'General'}
                  </div>
                </div>
                <h3 className="text-base font-bold text-slate-800 mb-1 group-hover:text-indigo-600 transition-colors">{template.name}</h3>
                <p className="text-slate-400 text-[11px] mb-4 line-clamp-2 leading-relaxed">{template.description || 'No description provided.'}</p>
                
                <div className="flex items-center gap-2 mb-4">
                   <button 
                    onClick={() => setViewingTemplate(template)}
                    className="flex-1 bg-indigo-600 hover:bg-indigo-700 text-white py-2 rounded-xl text-[10px] font-black uppercase tracking-widest transition-all flex items-center justify-center gap-1.5 shadow-lg shadow-indigo-100"
                   >
                     <Eye size={12} /> View Report
                   </button>
                   <button 
                    onClick={() => setShowReminderModal(template)}
                    className={`p-2 rounded-xl transition-all border ${template.reminder_config?.enabled ? 'bg-amber-50 text-amber-600 border-amber-100' : 'bg-slate-50 text-slate-400 border-transparent hover:border-slate-200'}`}
                    title="Config Reminder"
                   >
                     <Bell size={14} />
                   </button>
                   <button 
                    onClick={() => handleDeleteTemplate(template._id)}
                    className="p-2 bg-rose-50 text-rose-600 rounded-xl hover:bg-rose-600 hover:text-white transition-all border border-transparent hover:border-rose-100"
                    title="Delete Template"
                   >
                     <Trash2 size={14} />
                   </button>
                </div>

                <div className="flex items-center justify-between mt-auto pt-3 border-t border-slate-50">
                  <span className="text-[10px] font-bold text-slate-400">Updated {new Date(template.updated_at).toLocaleDateString()}</span>
                  <button onClick={() => handleEditTemplate(template)} className="text-indigo-600 font-black text-[10px] uppercase tracking-widest hover:underline flex items-center gap-1">
                    Manage Structure <Plus size={10} />
                  </button>
                </div>
              </div>
            ))}

            {templates.length === 0 && (
              <div className="col-span-full py-20 text-center bg-white rounded-2xl border-2 border-dashed border-slate-200">
                <div className="bg-slate-50 w-16 h-16 rounded-full flex items-center justify-center mx-auto mb-4">
                  <svg className="w-8 h-8 text-slate-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                </div>
                <h3 className="text-slate-700 font-bold text-lg">No Templates Found</h3>
                <p className="text-slate-400 mb-6">Start by creating your first performance tracking template.</p>
                <button
                  onClick={() => setIsAdding(true)}
                  className="text-indigo-600 font-bold hover:underline"
                >
                  Create Now
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Permissions & Node Editor Modal */}
      {editingNode && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-[2px] flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-[2rem] shadow-2xl w-full max-w-xl overflow-hidden animate-in fade-in zoom-in duration-200 border border-slate-200">
            <div className="p-6 border-b border-slate-50 flex justify-between items-center bg-slate-50/50">
              <div>
                <h3 className="text-lg font-black text-slate-800 uppercase tracking-tight">KPI Settings</h3>
                <p className="text-slate-400 text-[11px] font-bold uppercase tracking-widest mt-1">Configure <span className="text-indigo-600">{editingNode.node.name}</span></p>
              </div>
              <button onClick={() => setEditingNode(null)} className="text-slate-400 hover:text-slate-600 transition-colors p-1.5 hover:bg-white rounded-full shadow-sm border border-slate-100">
                <X size={20} />
              </button>
            </div>

            <div className="p-8 max-h-[60vh] overflow-y-auto no-scrollbar">
              {/* Anonymity Toggle */}
              <div className="bg-indigo-50/30 p-4 rounded-2xl border border-indigo-100/50 mb-6 flex items-center justify-between">
                <div className="flex gap-3 items-center">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${editingNode.node.is_anonymous ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-100' : 'bg-white text-indigo-400 shadow-sm border border-indigo-50'}`}>
                    {editingNode.node.is_anonymous ? <Lock size={16} /> : <Unlock size={16} />}
                  </div>
                  <div>
                    <h4 className="text-[13px] font-black text-slate-800 uppercase tracking-tight">Anonymous Submission</h4>
                    <p className="text-[10px] text-slate-400 font-bold uppercase tracking-wider">Mask identity for Team Engagement</p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    const newAnon = !editingNode.node.is_anonymous;
                    updateNode(editingNode.path, { is_anonymous: newAnon });
                    setEditingNode({ ...editingNode, node: { ...editingNode.node, is_anonymous: newAnon } });
                  }}
                  className={`w-12 h-6.5 rounded-full transition-all relative ${editingNode.node.is_anonymous ? 'bg-indigo-600' : 'bg-slate-200'}`}
                >
                  <div className={`absolute top-0.5 w-5.5 h-5.5 bg-white rounded-full shadow-sm transition-all ${editingNode.node.is_anonymous ? 'left-6' : 'left-0.5'}`} />
                </button>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                {/* Fillers Section */}
                <div>
                  <h4 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
                    <Edit3 size={12} className="text-emerald-500" /> Allowed Fillers
                  </h4>
                  <div className="space-y-1.5 mb-3 max-h-32 overflow-y-auto pr-1 custom-scrollbar">
                    {users.filter(u => editingNode.node.allowed_fillers?.includes(u._id)).map(u => (
                      <div key={u._id} className="flex items-center justify-between bg-emerald-50/50 text-emerald-700 px-2.5 py-1.5 rounded-lg border border-emerald-100 text-[11px] font-bold">
                        <span className="truncate max-w-[120px]">{u.full_name}</span>
                        <button onClick={() => {
                          const newList = editingNode.node.allowed_fillers.filter(id => id !== u._id);
                          updateNode(editingNode.path, { allowed_fillers: newList });
                          setEditingNode({ ...editingNode, node: { ...editingNode.node, allowed_fillers: newList } });
                        }} className="hover:text-emerald-900 ml-1"><X size={12} /></button>
                      </div>
                    ))}
                    {(!editingNode.node.allowed_fillers || editingNode.node.allowed_fillers.length === 0) && (
                      <p className="text-[10px] text-slate-400 italic bg-slate-50 p-2.5 rounded-lg border border-dashed border-slate-200 text-center">Admin access only</p>
                    )}
                  </div>
                  <select
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const newList = [...(editingNode.node.allowed_fillers || []), e.target.value];
                      updateNode(editingNode.path, { allowed_fillers: [...new Set(newList)] });
                      setEditingNode({ ...editingNode, node: { ...editingNode.node, allowed_fillers: [...new Set(newList)] } });
                      e.target.value = '';
                    }}
                    className="w-full bg-slate-50 border border-slate-100 rounded-lg text-[10px] font-black text-slate-500 px-3 py-2 focus:ring-1 focus:ring-indigo-500 outline-none transition-all uppercase tracking-wider"
                  >
                    <option value="">+ Add Filler</option>
                    {users.map(u => <option key={u._id} value={u._id}>{u.full_name}</option>)}
                  </select>
                </div>

                {/* Viewers Section */}
                <div>
                  <h4 className="text-[10px] font-black text-slate-400 uppercase tracking-[0.2em] mb-3 flex items-center gap-2">
                    <Eye size={12} className="text-blue-500" /> Allowed Viewers
                  </h4>
                  <div className="space-y-1.5 mb-3 max-h-32 overflow-y-auto pr-1 custom-scrollbar">
                    {users.filter(u => editingNode.node.allowed_viewers?.includes(u._id)).map(u => (
                      <div key={u._id} className="flex items-center justify-between bg-blue-50/50 text-blue-700 px-2.5 py-1.5 rounded-lg border border-blue-100 text-[11px] font-bold">
                        <span className="truncate max-w-[120px]">{u.full_name}</span>
                        <button onClick={() => {
                          const newList = editingNode.node.allowed_viewers.filter(id => id !== u._id);
                          updateNode(editingNode.path, { allowed_viewers: newList });
                          setEditingNode({ ...editingNode, node: { ...editingNode.node, allowed_viewers: newList } });
                        }} className="hover:text-blue-900 ml-1"><X size={12} /></button>
                      </div>
                    ))}
                    {(!editingNode.node.allowed_viewers || editingNode.node.allowed_viewers.length === 0) && (
                      <p className="text-[10px] text-slate-400 italic bg-slate-50 p-2.5 rounded-lg border border-dashed border-slate-200 text-center">Everyone assigned</p>
                    )}
                  </div>
                  <select
                    onChange={(e) => {
                      if (!e.target.value) return;
                      const newList = [...(editingNode.node.allowed_viewers || []), e.target.value];
                      updateNode(editingNode.path, { allowed_viewers: [...new Set(newList)] });
                      setEditingNode({ ...editingNode, node: { ...editingNode.node, allowed_viewers: [...new Set(newList)] } });
                      e.target.value = '';
                    }}
                    className="w-full bg-slate-50 border border-slate-100 rounded-lg text-[10px] font-black text-slate-500 px-3 py-2 focus:ring-1 focus:ring-indigo-500 outline-none transition-all uppercase tracking-wider"
                  >
                    <option value="">+ Add Viewer</option>
                    {users.map(u => <option key={u._id} value={u._id}>{u.full_name}</option>)}
                  </select>
                </div>
              </div>
            </div>

            <div className="p-6 bg-slate-50/50 flex justify-end border-t border-slate-100">
              <button
                onClick={() => setEditingNode(null)}
                className="bg-slate-900 hover:bg-black text-white px-8 py-2.5 rounded-xl font-black shadow-lg shadow-slate-200 transition-all uppercase tracking-widest text-[10px]"
              >
                Close Settings
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Reminder Config Modal */}
      {showReminderModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-[60] flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl shadow-2xl w-full max-w-md overflow-hidden animate-in fade-in zoom-in duration-200">
            <div className="p-6 border-b border-slate-50 flex justify-between items-center bg-amber-50/30">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-amber-100 text-amber-600 rounded-xl">
                  <Bell size={20} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800">Reminder Settings</h3>
                  <p className="text-xs text-slate-500">{showReminderModal.name}</p>
                </div>
              </div>
              <button onClick={() => setShowReminderModal(null)} className="p-2 hover:bg-white rounded-xl transition-all text-slate-400"><X size={20} /></button>
            </div>

            <div className="p-6 space-y-6">
              <div className="flex items-center justify-between p-4 bg-slate-50 rounded-2xl border border-slate-100">
                <div>
                  <h4 className="text-sm font-bold text-slate-700">Enable Monthly Reminder</h4>
                  <p className="text-[10px] text-slate-400">Notify users to fill their achievements</p>
                </div>
                <button
                  onClick={() => {
                    const enabled = !showReminderModal.reminder_config?.enabled;
                    const updated = { ...showReminderModal, reminder_config: { ...showReminderModal.reminder_config, enabled } };
                    setShowReminderModal(updated);
                  }}
                  className={`w-12 h-6.5 rounded-full transition-all relative ${showReminderModal.reminder_config?.enabled ? 'bg-amber-500' : 'bg-slate-200'}`}
                >
                  <div className={`absolute top-0.5 w-5.5 h-5.5 bg-white rounded-full shadow-sm transition-all ${showReminderModal.reminder_config?.enabled ? 'left-6' : 'left-0.5'}`} />
                </button>
              </div>

              {showReminderModal.reminder_config?.enabled && (
                <div className="space-y-4 animate-in slide-in-from-top-2 duration-200">
                  <div>
                    <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 ml-1">Day of Month</label>
                    <select
                      value={showReminderModal.reminder_config?.day_of_month || 25}
                      onChange={(e) => {
                        const day = parseInt(e.target.value);
                        setShowReminderModal({ ...showReminderModal, reminder_config: { ...showReminderModal.reminder_config, day_of_month: day } });
                      }}
                      className="w-full bg-slate-50 border-slate-100 rounded-xl px-4 py-2.5 text-sm font-bold"
                    >
                      {[...Array(28)].map((_, i) => (
                        <option key={i + 1} value={i + 1}>{i + 1}{i === 0 ? 'st' : i === 1 ? 'nd' : i === 2 ? 'rd' : 'th'} of the month</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-[10px] font-black text-slate-500 uppercase tracking-widest mb-1.5 ml-1">Custom Message</label>
                    <textarea
                      value={showReminderModal.reminder_config?.message || ''}
                      onChange={(e) => setShowReminderModal({ ...showReminderModal, reminder_config: { ...showReminderModal.reminder_config, message: e.target.value } })}
                      placeholder="e.g. Friendly reminder to update your monthly performance scores!"
                      className="w-full bg-slate-50 border-slate-100 rounded-xl px-4 py-3 text-sm min-h-[100px] font-medium leading-relaxed"
                    />
                  </div>
                </div>
              )}
            </div>

            <div className="p-6 bg-slate-50/50 border-t border-slate-100 flex gap-3">
              <button onClick={() => setShowReminderModal(null)} className="flex-1 px-5 py-2.5 rounded-xl font-bold text-slate-500 hover:bg-slate-100 transition-all text-sm">Cancel</button>
              <button
                onClick={async () => {
                  try {
                    await ormService.updateTemplate(showReminderModal._id, { reminder_config: showReminderModal.reminder_config });
                    showSuccess('Reminder settings updated');
                    setShowReminderModal(null);
                    loadTemplates();
                  } catch (e) {
                    showError('Failed to update reminders');
                  }
                }}
                className="flex-1 bg-amber-500 hover:bg-amber-600 text-white px-5 py-2.5 rounded-xl font-bold shadow-lg shadow-amber-100 transition-all text-sm"
              >
                Save Changes
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Tabular Report View Modal */}
      {viewingTemplate && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-md z-[70] flex items-center justify-center p-4">
          <div className="bg-white rounded-[2.5rem] shadow-2xl w-full max-w-6xl max-h-[90vh] overflow-hidden flex flex-col animate-in fade-in zoom-in duration-300">
            {/* Header */}
            <div className="p-8 border-b border-slate-50 flex justify-between items-center bg-gradient-to-r from-indigo-50/50 to-white">
              <div>
                <div className="flex items-center gap-3 mb-1">
                  <div className="p-2 bg-indigo-600 text-white rounded-xl shadow-lg shadow-indigo-100">
                    <Layers size={24} />
                  </div>
                  <h3 className="text-2xl font-black text-slate-800 tracking-tight">{viewingTemplate.name}</h3>
                </div>
                <p className="text-slate-500 text-sm font-medium ml-12">Outcome Result Performance Report</p>
              </div>
              <div className="flex items-center gap-4">
                <button 
                  onClick={() => window.print()} 
                  className="flex items-center gap-2 px-6 py-3 bg-emerald-50 text-emerald-600 rounded-2xl font-bold text-sm hover:bg-emerald-100 transition-all border border-emerald-100"
                >
                  <Settings2 size={18} /> Download Report
                </button>
                <button onClick={() => setViewingTemplate(null)} className="p-3 hover:bg-slate-100 rounded-2xl transition-all text-slate-400">
                  <X size={24} />
                </button>
              </div>
            </div>

            {/* Table Content */}
            <div className="flex-1 overflow-auto p-8 custom-scrollbar" id="printable-orm-matrix">
              <div className="bg-white border border-slate-100 rounded-[2rem] overflow-hidden shadow-sm">
                <div className="print-title hidden print:block">
                  ORGANIZATION RESULT MATRIX (ORM) format
                </div>
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="bg-slate-50/80 border-b border-slate-100">
                      <th className="px-6 py-5 text-left text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Five-Parameters</th>
                      <th className="px-6 py-5 text-left text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Subs</th>
                      <th className="px-6 py-5 text-center text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Weightage</th>
                      <th className="px-6 py-5 text-center text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Target</th>
                      <th className="px-6 py-5 text-center text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Achievement</th>
                      <th className="px-6 py-5 text-center text-[10px] font-black text-slate-400 uppercase tracking-[0.2em]">Score</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-50">
                    {/* Recursive Table Rows Helper */}
                    {(() => {
                      const rows = [];
                      let grandTotalWeight = 0;
                      let grandTotalScore = 0;

                      viewingTemplate.structure.forEach((parameterNode) => {
                        let paramTotalWeight = 0;
                        let paramTotalScore = 0;
                        let paramTotalAchievement = 0;

                        const processSubItems = (node, depth = 0, parentPath = '') => {
                          const currentId = `${parentPath}${node.name}`;
                          
                          // Check if it's a leaf node (no children)
                          const isLeaf = !node.children || node.children.length === 0;
                          
                          // For parent nodes, achievement and score should be sums of children
                          // This requires calculating children first or recursively
                          let achievement = 0;
                          let weightedScore = 0;
                          let kpiScoreRaw = 0;

                          if (isLeaf) {
                            achievement = tempAchievements[currentId] || 0;
                            paramTotalAchievement += achievement;
                            const target = node.target_value || 0;
                            if (target > 0 && achievement > 0) {
                              if (node.formula_type === 'reverse') {
                                kpiScoreRaw = Math.min(100, (target / achievement) * 100);
                              } else {
                                kpiScoreRaw = Math.min(100, (achievement / target) * 100);
                              }
                            }
                            weightedScore = (kpiScoreRaw * node.weightage) / 100;
                            paramTotalWeight += node.weightage;
                            paramTotalScore += weightedScore;
                          }

                          rows.push(
                            <tr key={currentId} className={`${!isLeaf ? 'bg-slate-50/30' : ''} hover:bg-slate-50 transition-colors border-b border-slate-50`}>
                              <td className="px-6 py-4 text-[10px] font-bold text-slate-700">
                                {parameterNode.name}
                              </td>
                              <td className="px-6 py-4">
                                <div className="flex items-center gap-2" style={{ paddingLeft: `${depth * 16}px` }}>
                                  <div className={`w-1.5 h-1.5 rounded-full ${!isLeaf ? 'bg-indigo-600 scale-125' : 'bg-slate-300'} print:hidden`} />
                                  <span className={`${!isLeaf ? 'text-[11px] font-black text-indigo-900 uppercase' : 'text-[11px] font-bold text-slate-700'}`}>
                                    {node.name}
                                  </span>
                                </div>
                              </td>
                              <td className="px-6 py-4 text-center text-[11px] font-black text-slate-400">
                                {isLeaf ? node.weightage.toFixed(1) : ''}
                              </td>
                              <td className="px-6 py-4 text-center text-[11px] font-bold text-slate-700">
                                {isLeaf ? (node.target_value || '-') : ''}
                              </td>
                              <td className="px-6 py-4 text-center">
                                {isLeaf ? (
                                  <input 
                                    type="number" 
                                    value={tempAchievements[currentId] || ''}
                                    onChange={(e) => setTempAchievements({
                                      ...tempAchievements,
                                      [currentId]: parseFloat(e.target.value) || 0
                                    })}
                                    placeholder="0"
                                    className="w-20 bg-white border border-slate-200 rounded-lg px-2 py-1 text-xs font-black text-center focus:ring-2 focus:ring-indigo-500 outline-none"
                                  />
                                ) : (
                                  <span className="text-[10px] font-black text-slate-300 italic print:hidden">Sub-group</span>
                                )}
                              </td>
                              <td className="px-6 py-4 text-center">
                                {isLeaf ? (
                                  <span className={`text-xs font-black ${weightedScore > 0 ? 'text-indigo-600' : 'text-slate-300'} print:text-black`}>
                                    {weightedScore.toFixed(2)}
                                  </span>
                                ) : '-'}
                              </td>
                            </tr>
                          );

                          if (node.children && node.children.length > 0) {
                            node.children.forEach(child => processSubItems(child, depth + 1, `${currentId}_`));
                          }
                        };

                        // If it's a top-level node with children, process them
                        if (parameterNode.children && parameterNode.children.length > 0) {
                          parameterNode.children.forEach(child => processSubItems(child, 0, `${parameterNode.name}_`));
                        } else {
                          // Standard flat node
                          processSubItems(parameterNode, 0, '');
                        }

                        // Add Parameter Total Row
                        rows.push(
                          <tr key={`${parameterNode.name}-total`} className="bg-slate-50/50 font-black total-row">
                            <td colSpan={2} className="px-6 py-4 text-slate-800 text-[11px] uppercase tracking-wider">
                              {parameterNode.name} Total
                            </td>
                            <td className="px-6 py-4 text-center text-slate-800 text-[11px]">{paramTotalWeight.toFixed(1)}</td>
                            <td className="px-6 py-4 text-center text-slate-800 text-[11px]">{parameterNode.target_value || '-'}</td>
                            <td className="px-6 py-4 text-center text-slate-800 text-[11px]">{paramTotalAchievement || '-'}</td>
                            <td className="px-6 py-4 text-center text-indigo-700 text-sm print:text-black">
                              {paramTotalScore.toFixed(2)}
                            </td>
                          </tr>
                        );

                        grandTotalWeight += paramTotalWeight;
                        grandTotalScore += paramTotalScore;
                      });
                      
                      // Add Grand Total Row
                      rows.push(
                        <tr key="grand-total-row" className="bg-indigo-600 text-white font-black shadow-lg grand-total-row">
                          <td colSpan={2} className="px-6 py-5 text-sm uppercase tracking-[0.2em] print:text-black">Grand Total</td>
                          <td className="px-6 py-5 text-center text-sm print:text-black">{grandTotalWeight.toFixed(1)}</td>
                          <td colSpan={2} className="px-6 py-5"></td>
                          <td className="px-6 py-5 text-center text-lg print:text-black">
                            {grandTotalScore.toFixed(2)}
                          </td>
                        </tr>
                      );

                      return rows;
                    })()}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Footer */}
            <div className="p-8 border-t border-slate-50 bg-slate-50/30 flex justify-end gap-3">
              <button onClick={() => setViewingTemplate(null)} className="px-8 py-3 rounded-2xl font-bold text-slate-500 hover:bg-slate-100 transition-all text-sm uppercase tracking-widest">
                Close View
              </button>
              <button className="bg-indigo-600 hover:bg-indigo-700 text-white px-10 py-3 rounded-2xl font-black shadow-xl shadow-indigo-100 transition-all text-sm uppercase tracking-widest">
                Save & Update Scores
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Add styles for the classic ORM Matrix Print Layout
const printStyles = `
@media print {
  body * {
    visibility: hidden;
  }
  #printable-orm-matrix, #printable-orm-matrix * {
    visibility: visible;
  }
  #printable-orm-matrix {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    visibility: visible;
  }
  .no-print {
    display: none !important;
  }
  table {
    border-collapse: collapse !important;
    width: 100% !important;
  }
  th, td {
    border: 1px solid black !important;
    padding: 4px 8px !important;
    color: black !important;
    font-size: 10pt !important;
    background: white !important;
  }
  th {
    background-color: #d9ead3 !important;
    font-weight: bold !important;
    text-align: center !important;
  }
  .total-row {
    background-color: #d9ead3 !important;
    font-weight: bold !important;
  }
  .grand-total-row {
    background-color: #d9ead3 !important;
    font-weight: bold !important;
  }
  input {
    border: none !important;
    background: transparent !important;
    text-align: center !important;
    width: 100% !important;
    font-weight: bold !important;
  }
  .print-title {
    background-color: #d9ead3 !important;
    border: 1px solid black !important;
    padding: 8px !important;
    font-weight: bold !important;
    text-align: left !important;
    font-size: 14pt !important;
  }
}
`;

const styleTag = document.createElement('style');
styleTag.innerHTML = printStyles;
document.head.appendChild(styleTag);

export default ORMTemplateManager;
