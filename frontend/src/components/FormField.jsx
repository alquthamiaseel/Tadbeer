// ---------------------------------------------------------------------------
// FormField
// ---------------------------------------------------------------------------
// A reusable labeled input used on the Login and Register pages.
// It renders: a label, then an input with a small icon on the left.
// Having this in one place means the login/register pages stay short,
// and any styling changes only need to happen here.
// ---------------------------------------------------------------------------
export default function FormField({
  label,
  icon: Icon,
  type = 'text',
  placeholder,
  value,
  onChange,
  name,
  required = true,
}) {
  return (
    <div>
      <label className="mb-2 block text-sm font-semibold text-white">
        {label}
      </label>
      <div className="relative">
        {/* Icon sits absolutely inside the input's left padding area */}
        <Icon className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-slate-400" />
        <input
          type={type}
          name={name}
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          required={required}
          className="w-full rounded-lg border border-slate-700 bg-slate-900/60 py-3 pl-10 pr-3 text-white placeholder-slate-500 outline-none focus:border-teal-400"
        />
      </div>
    </div>
  )
}
