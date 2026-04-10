# Use official Node.js image
FROM node:20

# Set working directory
WORKDIR /app

# Copy package.json and lock files
COPY package*.json ./

# Install dependencies (using npm since package-lock.json exists)
RUN npm install

# Copy the rest of the frontend code
COPY . .

# Expose the port Vite dev server runs on (from vite.config.ts)
EXPOSE 8080

# Command to run Vite in dev mode with host exposed
CMD ["npm", "run", "dev", "--", "--host"]
