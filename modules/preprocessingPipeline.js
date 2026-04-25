/**
 * Flexible Preprocessing Pipeline for Primary Forest Finder
 *
 * Allows chaining of preprocessing operations with custom inputs beyond binary images.
 * Supports continuous values, weighted combinations, and custom filters.
 */

/**
 * @typedef {Object} PreprocessConfig
 * @property {string} name - Unique name for this preprocessing pipeline
 * @property {Array<Object>} steps - Array of preprocessing steps to apply in order
 * @property {boolean} [normalizeOutput] - Whether to normalize final output to 0-1 (default: true)
 * @property {number} [outputMin] - Minimum output value (default: 0)
 * @property {number} [outputMax] - Maximum output value (default: 1)
 */

/**
 * @typedef {Object} PreprocessStep
 * @property {string} type - Type of operation: 'threshold', 'distance', 'multiply', 'add', 'max', 'min', 'custom'
 * @property {string|ee.Image} input - Input layer name or ee.Image
 * @property {Object} params - Operation-specific parameters
 * @property {string} [output] - Variable name to store result (auto-generated if not provided)
 */

var PreprocessingPipeline = (function() {

  // Store for preprocessing configurations
  var configs = {};
  var variables = {};
  var executionLog = [];

  /**
   * Register a preprocessing configuration
   */
  function registerConfig(configName, config) {
    if (!config.name) config.name = configName;
    if (!config.steps) config.steps = [];
    if (typeof config.normalizeOutput === 'undefined') config.normalizeOutput = true;
    config.outputMin = config.outputMin || 0;
    config.outputMax = config.outputMax || 1;

    configs[configName] = config;
    return config;
  }

  /**
   * Execute a preprocessing pipeline
   */
  function execute(configName, inputs) {
    if (!configs[configName]) {
      throw new Error('Preprocessing config not found: ' + configName);
    }

    variables = {};
    executionLog = [];

    var config = configs[configName];

    // Load input variables
    for (var key in inputs) {
      if (inputs.hasOwnProperty(key)) {
        variables[key] = inputs[key];
      }
    }

    log('Starting pipeline: ' + configName);

    // Execute each step
    for (var i = 0; i < config.steps.length; i++) {
      var step = config.steps[i];
      executeStep(step, i);
    }

    // Get final output
    var result = variables[config.steps[config.steps.length - 1].output];

    // Normalize if requested
    if (config.normalizeOutput && result) {
      result = result.subtract(config.outputMin)
        .divide(config.outputMax - config.outputMin);
      log('Normalized output to [' + config.outputMin + ', ' + config.outputMax + ']');
    }

    log('Pipeline complete');
    return result;
  }

  /**
   * Execute a single preprocessing step
   */
  function executeStep(step, index) {
    var output = step.output || ('step_' + index);
    var input = variables[step.input] || step.input;

    log('Step ' + (index + 1) + ': ' + step.type + ' -> ' + output);

    var result;

    switch(step.type) {
      case 'threshold':
        result = executeThreshold(input, step.params);
        break;

      case 'distance':
        result = executeDistance(input, step.params);
        break;

      case 'multiply':
        result = executeMultiply(input, step.params);
        break;

      case 'add':
        result = executeAdd(input, step.params);
        break;

      case 'max':
        result = executeMax(input, step.params);
        break;

      case 'min':
        result = executeMin(input, step.params);
        break;

      case 'combine':
        result = executeCombine(step.params);
        break;

      case 'mask':
        result = executeMask(input, step.params);
        break;

      case 'remap':
        result = executeRemap(input, step.params);
        break;

      default:
        throw new Error('Unknown step type: ' + step.type);
    }

    variables[output] = result;
  }

  /**
   * Binary threshold operation
   * params: {value: number}
   */
  function executeThreshold(input, params) {
    var threshold = params.value;
    return input.gte(threshold).selfMask();
  }

  /**
   * Distance buffer operation
   * params: {threshold: number, maxDistance: number, neighborhood: number, fastBuffer: boolean}
   */
  function executeDistance(input, params) {
    var threshold = params.threshold || 1000;
    var fastBuffer = params.fastBuffer !== false;
    var neighborhood = params.neighborhood || 170;

    var distBuffer;
    if (fastBuffer) {
      distBuffer = input.fastDistanceTransform({neighborhood: neighborhood})
        .sqrt()
        .multiply(ee.Image.pixelArea().sqrt());
    } else {
      distBuffer = ee.Image(1).cumulativeCost({
        source: input,
        maxDistance: threshold * 1.2
      });
    }

    return distBuffer.lte(threshold);
  }

  /**
   * Multiply operation
   * params: {multiplier: number} or {by: ee.Image}
   */
  function executeMultiply(input, params) {
    if (params.multiplier) {
      return input.multiply(params.multiplier);
    } else if (params.by) {
      return input.multiply(params.by);
    }
    return input;
  }

  /**
   * Add operation
   * params: {value: number} or {to: ee.Image}
   */
  function executeAdd(input, params) {
    if (typeof params.value === 'number') {
      return input.add(params.value);
    } else if (params.to) {
      return input.add(params.to);
    }
    return input;
  }

  /**
   * Max operation
   * params: {with: ee.Image|string} - Compare input with another image
   */
  function executeMax(input, params) {
    var other = typeof params.with === 'string' ? variables[params.with] : params.with;
    return input.max(other);
  }

  /**
   * Min operation
   * params: {with: ee.Image|string} - Compare input with another image
   */
  function executeMin(input, params) {
    var other = typeof params.with === 'string' ? variables[params.with] : params.with;
    return input.min(other);
  }

  /**
   * Combine multiple layers
   * params: {layers: Array<string>, operator: 'and'|'or'|'add'|'mean'|'median'|'max'|'min', weights: Array<number>}
   */
  function executeCombine(params) {
    var operator = params.operator || 'or';
    var layers = params.layers.map(function(l) {
      return typeof l === 'string' ? variables[l] : l;
    });

    if (!layers.length) throw new Error('No layers to combine');

    var result = layers[0];

    switch(operator) {
      case 'and':
        for (var i = 1; i < layers.length; i++) {
          result = result.and(layers[i]);
        }
        break;

      case 'or':
        for (var i = 1; i < layers.length; i++) {
          result = result.or(layers[i]);
        }
        break;

      case 'add':
        for (var i = 1; i < layers.length; i++) {
          result = result.add(layers[i]);
        }
        break;

      case 'mean':
        var sum = result;
        for (var i = 1; i < layers.length; i++) {
          sum = sum.add(layers[i]);
        }
        result = sum.divide(layers.length);
        break;

      case 'weighted':
        if (!params.weights || params.weights.length !== layers.length) {
          throw new Error('Weighted combine requires weights array matching layer count');
        }
        result = result.multiply(params.weights[0]);
        for (var i = 1; i < layers.length; i++) {
          result = result.add(layers[i].multiply(params.weights[i]));
        }
        break;

      case 'max':
        for (var i = 1; i < layers.length; i++) {
          result = result.max(layers[i]);
        }
        break;

      case 'min':
        for (var i = 1; i < layers.length; i++) {
          result = result.min(layers[i]);
        }
        break;

      default:
        throw new Error('Unknown combine operator: ' + operator);
    }

    return result;
  }

  /**
   * Apply a mask to an image
   * params: {mask: ee.Image|string}
   */
  function executeMask(input, params) {
    var mask = typeof params.mask === 'string' ? variables[params.mask] : params.mask;
    return input.updateMask(mask);
  }

  /**
   * Remap values
   * params: {from: Array<number>, to: Array<number>}
   */
  function executeRemap(input, params) {
    return input.remap(params.from, params.to);
  }

  /**
   * Log execution messages
   */
  function log(message) {
    executionLog.push(message);
  }

  /**
   * Get execution log
   */
  function getLog() {
    return executionLog;
  }

  /**
   * Get registered config
   */
  function getConfig(name) {
    return configs[name];
  }

  /**
   * Get all registered configs
   */
  function getAllConfigs() {
    return Object.keys(configs).map(function(k) { return configs[k]; });
  }

  /**
   * Get a variable by name (for debugging)
   */
  function getVariable(name) {
    return variables[name];
  }

  // Public API
  return {
    registerConfig: registerConfig,
    execute: execute,
    getConfig: getConfig,
    getAllConfigs: getAllConfigs,
    getVariable: getVariable,
    getLog: getLog
  };
})();

// Export
if (typeof module !== 'undefined' && module.exports) {
  module.exports = PreprocessingPipeline;
}
