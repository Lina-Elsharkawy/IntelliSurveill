const router = require('./src/routes/index');

function printRoutes(route, basePath = '') {
  if (route.route) {
    // This is an endpoint
    const path = basePath + route.route.path;
    const methods = Object.keys(route.route.methods).filter(m => route.route.methods[m]).map(m => m.toUpperCase());
    methods.forEach(m => console.log(`${m} ${path}`));
  } else if (route.name === 'router' && route.handle.stack) {
    // This is a nested router
    const newBasePath = basePath + (route.regexp.source !== '^\\/?$' ? 
      route.regexp.source.replace('^\\/', '/').replace('\\/?(?=\\/|$)', '').replace('^\\/', '/') : '');
    // It's hard to get exact path from regexp, let's just use a simpler approach:
    // since we use router.use('/path', nestedRouter), let's see if we can get it.
  }
}

// better approach: use express-list-endpoints
