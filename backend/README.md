# Backend 

This repository contains the backend code for the Graduation Project application. It is a RESTful API built with Node.js and Express, using PostgreSQL as the database and Sequelize as the ORM.

## Tech Stack

*   **Runtime**: [Node.js](https://nodejs.org/)
*   **Framework**: [Express.js](https://expressjs.com/)
*   **Database**: [PostgreSQL](https://www.postgresql.org/)
*   **ORM**: [Sequelize](https://sequelize.org/)

## Prerequisites

Ensure you have the following installed:

*   Node.js (v18+ recommended)
*   PostgreSQL running locally or accessible via network

## Setup

1.  **Clone the repository** (if not already done).
2.  **Navigate to the backend directory**:
    ```bash
    cd backend
    ```
3.  **Install dependencies**:
    ```bash
    npm install
    ```
4.  **Configuration**:
    *   Create a `.env` file in the root of the backend directory.
    *   Copy the contents from `.env.example` to `.env`.
    *   Update the database credentials and other environment variables as needed.

    ```bash
    cp .env.example .env
    ```

## Running the Application

### Development Mode
Runs the server with `nodemon` for hot-reloading.
```bash
npm run dev
```

### Production Mode
Runs the server using standard node command.
```bash
npm start
```

## Project Structure

*   `src/server.js`: Entry point of the application.
*   `src/controllers/`: Contains logic for handling API requests.
*   `src/models/`: Sequelize models defining database schemas.
*   `src/routes/`: Defines API endpoints and links them to controllers.
*   `src/middleware/`: Custom middleware (e.g., error handling, validation).
*   `src/db/`: Database connection setup.
*   `src/config/`: Configuration files.
