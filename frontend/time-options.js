(function(root){
  const START_HOUR = 6;
  const END_HOUR = 22;
  const STEP_MINUTES = 30;
  const BLANK_LABEL = 'Select time';

  function pad(n){ return n < 10 ? '0'+n : ''+n; }

  function buildTimeOptions(){
    const options = [];
    for(let h = START_HOUR; h <= END_HOUR; h++){
      for(let m = 0; m < 60; m += STEP_MINUTES){
        if(h === END_HOUR && m > 0) break;
        options.push(pad(h)+':'+pad(m));
      }
    }
    return options;
  }

  const TIME_OPTIONS = buildTimeOptions();

  const api = {TIME_OPTIONS, BLANK_LABEL};
  root.TimeOptions = api;
  if(typeof module !== 'undefined' && module.exports){
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
