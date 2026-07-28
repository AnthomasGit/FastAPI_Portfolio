# ==========================================
# STAGE 1: Build the Vite Application
# ==========================================
FROM node:24-alpine AS builder

WORKDIR /app

# Copy package files and install dependencies
# Doing this first leverages Docker layer caching to speed up future builds
COPY package*.json ./
RUN npm install

# Copy the rest of the source code
COPY . .

# Build the project (Vite outputs to a 'dist' folder)
RUN npm run build

# ==========================================
# STAGE 2: Serve with Nginx
# ==========================================
FROM nginx:alpine

# Copy the compiled static files from the builder stage
# Notice we target /app/dist because Vite uses 'dist' instead of 'build'
COPY --from=builder /app/dist /usr/share/nginx/html

# Replace the default Nginx config with our custom one (created below)
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80 (This is the port your K8s Service and Ingress will target)
EXPOSE 80

# Start Nginx
CMD ["nginx", "-g", "daemon off;"]