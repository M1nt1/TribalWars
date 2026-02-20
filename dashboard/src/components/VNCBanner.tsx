interface Props {
  botState: string;
  vncUrl?: string;
}

export function VNCBanner({ botState, vncUrl }: Props) {
  // Show banner when bot is stopped and not yet logged in
  if (botState !== 'stopped') return null;

  const url = vncUrl || `${window.location.protocol}//${window.location.hostname}:6080/vnc.html`;

  return (
    <div className="vnc-banner">
      Login required — open
      <a href={url} target="_blank" rel="noopener noreferrer">
        noVNC
      </a>
      {' '}to access the browser for login / CAPTCHA
    </div>
  );
}
