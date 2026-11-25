import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { AppProvider } from './store';
import { UIModeProvider } from './mode';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <UIModeProvider>
      <AppProvider>
        <App />
      </AppProvider>
    </UIModeProvider>
  </React.StrictMode>,
);
