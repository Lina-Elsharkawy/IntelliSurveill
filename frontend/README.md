# Frontend Dashboard

This directory contains the frontend application for the Graduation Project. It allows users to visualize streaming data, configure anomaly detection rules, and view system logs.

## Tech Stack

*   **Framework**: [React](https://react.dev/) + [Vite](https://vitejs.dev/)
*   **Language**: [TypeScript](https://www.typescriptlang.org/)
*   **Styling**: [Tailwind CSS](https://tailwindcss.com/)
*   **UI Library**: [Shadcn UI](https://ui.shadcn.com/)
*   **Icons**: [Lucide React](https://lucide.dev/)
*   **Data Fetching**: [TanStack Query](https://tanstack.com/query/latest)

## Prerequisites

*   Node.js (v18+ recommended)

## Setup

1.  **Navigate to the frontend directory**:
    ```bash
    cd frontend
    ```
2.  **Install dependencies**:
    ```bash
    npm install
    ```

## Running the Application

### Development Server
Starts the local development server at `http://localhost:8080` (or similar port).
```bash
npm run dev
```

### Production Build
Builds the application for production deployment.
```bash
npm run build
```

### Linting
Runs ESLint to check for code quality issues.
```bash
npm run lint
```

## Project Structure

*   `src/main.tsx`: Entry point of the React application.
*   `src/App.tsx`: Main component setup.
*   `src/pages/`: Contains page components corresponding to routes (e.g., Dashboard, Settings).
*   `src/components/`: Reusable UI components.
    *   `src/components/ui/`: Primitive components from Shadcn UI.
*   `src/hooks/`: Custom React hooks for logic reuse.
*   `src/lib/`: Utility functions and helper classes (e.g., `utils.ts`).
*   `src/assets/`: Static assets like images and fonts.
