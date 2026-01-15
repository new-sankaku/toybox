interface FooterProps {
  message?: string
}

export default function Footer({ message }: FooterProps): JSX.Element {
  return (
    <footer className="bg-nier-bg-footer text-nier-text-footer px-6 py-3 flex justify-between items-center border-t-2 border-[#3D3A33]">
      <div className="flex items-center gap-2">
        <span className="w-0.5 h-4 bg-nier-text-footer" />
        <span className="text-nier-small">
          {message || 'プロジェクトを選択してください。'}
        </span>
      </div>

      <div className="flex gap-6 text-nier-small">
        <div className="flex items-center gap-1.5">
          <span className="opacity-70">↕</span>
          <span>選択</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="opacity-70">◉</span>
          <span>決定</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="opacity-70">⊗</span>
          <span>戻る</span>
        </div>
      </div>
    </footer>
  )
}
