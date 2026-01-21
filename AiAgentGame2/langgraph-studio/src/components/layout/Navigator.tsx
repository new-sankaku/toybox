import { useNavigatorStore } from '../../stores/navigatorStore'

export default function Navigator(): JSX.Element | null {
  const { isVisible, currentMessage, dismissMessage } = useNavigatorStore()

  if (!isVisible || !currentMessage) {
    return null
  }

  // Priority-based styling
  const getPriorityClass = () => {
    if (currentMessage.source !== 'server') return ''
    switch (currentMessage.priority) {
      case 'critical': return 'priority-critical'
      case 'high': return 'priority-high'
      default: return ''
    }
  }

  const getSourceIndicator = () => {
    if (currentMessage.source === 'server') {
      return <span className="message-source-badge">SERVER</span>
    }
    return null
  }

  return (
    <div className={`navigator-overlay ${getPriorityClass()}`} onClick={dismissMessage}>
      {/* Navigator Character - Right Bottom */}
      <div className="navigator-character">
        <div className="navigator-frame">
          {/* Header */}
          <div className="navigator-header">
            <span className="navigator-diamond">◇</span>
            <span className="navigator-title">OPERATOR</span>
            <div className="navigator-status">
              <span className="navigator-status-dot"></span>
              <span className="navigator-status-text">ONLINE</span>
            </div>
          </div>

          {/* Character Portrait */}
          <div className="navigator-portrait">
            <div className="navigator-portrait-inner">
              {/* Stylized operator icon */}
              <svg viewBox="0 0 100 100" className="navigator-icon">
                {/* Head circle */}
                <circle cx="50" cy="35" r="20" fill="none" stroke="currentColor" strokeWidth="2" />
                {/* Eyes */}
                <circle cx="43" cy="32" r="3" fill="currentColor" />
                <circle cx="57" cy="32" r="3" fill="currentColor" />
                {/* Headset */}
                <path d="M25 35 Q25 15, 50 15 Q75 15, 75 35" fill="none" stroke="currentColor" strokeWidth="2" />
                <rect x="20" y="30" width="8" height="12" rx="2" fill="currentColor" opacity="0.7" />
                <rect x="72" y="30" width="8" height="12" rx="2" fill="currentColor" opacity="0.7" />
                {/* Mic */}
                <path d="M28 42 Q15 45, 20 55 L25 53" fill="none" stroke="currentColor" strokeWidth="2" />
                <circle cx="20" cy="55" r="4" fill="currentColor" opacity="0.7" />
                {/* Body/shoulders */}
                <path d="M30 55 Q50 65, 70 55 L75 75 Q50 85, 25 75 Z" fill="currentColor" opacity="0.3" stroke="currentColor" strokeWidth="1.5" />
                {/* Collar details */}
                <path d="M40 58 L50 68 L60 58" fill="none" stroke="currentColor" strokeWidth="1.5" />
              </svg>
            </div>
            {/* Scan line effect */}
            <div className="navigator-scanline"></div>
          </div>

          {/* Footer */}
          <div className="navigator-footer">
            <div className="navigator-line"></div>
            <span className="navigator-label">TRANSMISSION</span>
            <div className="navigator-line"></div>
          </div>
        </div>
      </div>

      {/* Dialogue Bar - Bottom */}
      <div className={`dialogue-bar ${getPriorityClass()}`}>
        <div className="dialogue-content">
          <span className="dialogue-speaker">
            <span className="dialogue-diamond">◇</span>
            {currentMessage.speaker}
            {getSourceIndicator()}
          </span>
          <p className="dialogue-text">{currentMessage.text}</p>
        </div>
        <div className="dialogue-hint">Click to continue...</div>
      </div>
    </div>
  )
}
