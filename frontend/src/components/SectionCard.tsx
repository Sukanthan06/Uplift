interface SectionCardProps {
  title: string
  subtitle?: string
  children: React.ReactNode
}

export default function SectionCard({ title, subtitle, children }: SectionCardProps) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white p-5">
      <h2 className="text-sm font-semibold text-gray-900">{title}</h2>
      {subtitle && <p className="mt-0.5 text-xs text-gray-500">{subtitle}</p>}
      <div className="mt-4">{children}</div>
    </section>
  )
}
