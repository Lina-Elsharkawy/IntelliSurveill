# Lab Access Control Frontend

A React-based web application for the Lab Access Control system.

## Tech Stack

- **Build Tool**: [Vite](https://vitejs.dev/)
- **Framework**: [React 18](https://react.dev/)
- **Language**: [TypeScript](https://www.typescriptlang.org/)
- **Styling**: [Tailwind CSS](https://tailwindcss.com/)
- **UI Components**: [shadcn/ui](https://ui.shadcn.com/)
- **State Management**: [TanStack Query](https://tanstack.com/query)
- **Forms**: [React Hook Form](https://react-hook-form.com/) + [Zod](https://zod.dev/)
- **Routing**: [React Router](https://reactrouter.com/)
- **Testing**: [Vitest](https://vitest.dev/)

## Prerequisites

- Node.js v18+ ([install with nvm](https://github.com/nvm-sh/nvm))
- npm or bun

## Getting Started

1. **Install dependencies**:
   ```bash
   npm install
   ```

2. **Configure environment**:
   Create a `.env` file in the frontend root:
   ```env
   VITE_API_BASE_URL=http://localhost:3000
   ```

3. **Start development server**:
   ```bash
   npm run dev
   ```
   The app will be available at `http://localhost:8080`

## Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start development server with hot-reload |
| `npm run build` | Build production bundle |
| `npm run build:dev` | Build development bundle |
| `npm run preview` | Preview production build locally |
| `npm run lint` | Run ESLint |
| `npm run test` | Run tests in watch mode |
| `npm run test:run` | Run tests once |

## Project Structure

```
frontend/
├── src/
│   ├── __tests__/          # Test files
│   │   ├── mocks/          # Mock utilities for testing
│   │   ├── services/       # Service test files
│   │   └── setup.ts        # Global test setup
│   ├── components/         # React components
│   │   └── ui/             # shadcn/ui components
│   ├── hooks/              # Custom React hooks
│   ├── lib/                # Utility functions
│   │   ├── api.ts          # Centralized API client
│   │   └── utils.ts        # General utilities
│   ├── pages/              # Page components
│   ├── services/           # API service functions
│   │   ├── anomalies.ts    # Anomalies API
│   │   ├── cameras.ts      # Cameras API
│   │   ├── departments.ts  # Departments API
│   │   ├── detected-people.ts # Detected People API
│   │   ├── employees.ts    # Employees API
│   │   ├── health.ts       # Health check API
│   │   ├── labs.ts         # Labs API
│   │   ├── logs.ts         # Logs API
│   │   ├── rag.ts          # RAG query API
│   │   ├── schedules.ts    # Schedules API
│   │   ├── visitors.ts     # Visitors API
│   │   └── index.ts        # Barrel export
│   ├── types/              # TypeScript type definitions
│   │   └── types.ts        # All API entity types
│   ├── App.tsx             # Root component
│   └── main.tsx            # Entry point
├── public/                 # Static assets
├── vitest.config.ts        # Vitest configuration
├── vite.config.ts          # Vite configuration
└── tailwind.config.ts      # Tailwind configuration
```

## API Services

All API calls are centralized through `src/lib/api.ts` which handles:
- JWT authentication (token from `localStorage`)
- Base URL configuration via `VITE_API_BASE_URL`
- Error handling

### Usage Example

```typescript
import { getAllCameras, createCamera } from '@/services';

// Fetch all cameras
const cameras = await getAllCameras();

// Create a new camera
const newCamera = await createCamera({
  name: 'Lobby Camera',
  location: 'Main Entrance',
  lab_id: 1
});
```

### Available Services

| Service | Endpoints |
|---------|-----------|
| `anomalies` | getAll, getById, delete |
| `cameras` | getAll, getById, create, update, delete |
| `departments` | getAll, getById, create, update, delete |
| `detected-people` | getAll, getById |
| `employees` | getAll, getById, create, update, delete |
| `health` | checkHealth |
| `labs` | getAll, getById, create, update, delete |
| `logs` | getAll, getById, byCamera, byEventType, byAuthorization, byLocation, byAnomaly |
| `rag` | queryRAG |
| `schedules` | getAll, getById, create, update, delete |
| `visitors` | getAll, getById, create, update, delete |

## Testing

Tests are written using Vitest with mocked fetch calls.

```bash
# Run tests in watch mode
npm run test

# Run tests once
npm run test:run
```

Test files are located in `src/__tests__/services/` and follow the naming convention `*.test.ts`.

## Adding New Components

This project uses [shadcn/ui](https://ui.shadcn.com/). To add a new component:

```bash
npx shadcn@latest add <component-name>
```

